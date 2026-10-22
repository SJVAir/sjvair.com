from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.meta import catalog, coverage
from camp.api.v2.meta.endpoints import CoverageEndpoint
from camp.apps.entries.models import PM10, PM25, Humidity, Temperature
from camp.apps.hms.models import Fire
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import MonitorSummary, RegionSummary
from camp.utils.test import get_response_data

coverage_view = CoverageEndpoint.as_view()

PUBLISHED = 'PM25_EPA_Oct2021'  # purpleair/pm25 in default-calibrations.yaml

STATS = {
    'count': 30, 'expected_count': 30, 'sum_value': 300.0, 'sum_of_squares': 3000.0,
    'minimum': 10.0, 'maximum': 10.0, 'mean': 10.0, 'stddev': 0.0, 'p25': 10.0, 'p75': 10.0,
    'tdigest': {'C': [], 'n': 0},
}


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def make_entry(model, monitor, timestamp, **kwargs):
    return model.objects.create(
        monitor=monitor, timestamp=timestamp, location='outside', value=Decimal('10'), **kwargs
    )


def make_latest(monitor, entry):
    return LatestEntry.objects.create(
        monitor=monitor, entry_type=entry.entry_type, entry_id=entry.pk,
        stage=entry.stage, processor=entry.processor, timestamp=entry.timestamp,
    )


def make_monitor_summary(monitor, timestamp, entry_type='pm25', resolution='hour'):
    return MonitorSummary.objects.create(
        monitor=monitor, timestamp=timestamp, entry_type=entry_type,
        resolution=resolution, processor='', is_complete=True, **STATS,
    )


def make_region_summary(region, timestamp, entry_type='pm25', resolution='hour'):
    return RegionSummary.objects.create(
        region=region, timestamp=timestamp, entry_type=entry_type,
        resolution=resolution, station_count=1, weight=1.0, **STATS,
    )


class CoverageTestCase(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml', 'default-calibrations.yaml']

    def setUp(self):
        cache.clear()
        self.monitor = PurpleAir.objects.first()
        self.county = Region.all_objects.get(type=Region.Type.COUNTY, external_id='06019')

    def get(self, **params):
        response = coverage_view(RequestFactory().get(reverse('api:v2:meta:coverage'), params))
        return response, get_response_data(response)


class MonitorSpanTests(CoverageTestCase):
    def published_data(self):
        # Raw on Dec 31 (Pacific), the published processor from Jan 1 22:00
        # Pacific (Jan 2 UTC) to Jan 1 23:30 Pacific (also Jan 2 UTC).
        make_entry(PM25, self.monitor, utc(2026, 1, 1, 4, 0), sensor='a', stage='raw')
        first = make_entry(PM25, self.monitor, utc(2026, 1, 2, 6, 0), stage='calibrated', processor=PUBLISHED)
        last = make_entry(PM25, self.monitor, utc(2026, 1, 2, 7, 30), stage='calibrated', processor=PUBLISHED)
        raw_later = make_entry(PM25, self.monitor, utc(2026, 1, 3, 12, 0), sensor='a', stage='raw')
        make_latest(self.monitor, last)
        make_latest(self.monitor, raw_later)
        return first, last

    def test_monitor_span_uses_published_processor_and_pacific_dates(self):
        self.published_data()
        with timezone.override(None):
            span = coverage.monitor_span(self.monitor, 'pm25')
        assert span == {'first': date(2026, 1, 1), 'last': date(2026, 1, 1)}

    def test_monitor_span_query_count(self):
        self.published_data()
        with self.assertNumQueries(3):  # published-pair lookup, MIN, LatestEntry
            coverage.monitor_span(self.monitor, 'pm25')

    def test_unpublished_pair_counts_any_stage(self):
        make_entry(PM10, self.monitor, utc(2026, 2, 1, 12, 0), sensor='a', stage='raw')
        make_entry(PM10, self.monitor, utc(2026, 2, 3, 12, 0), sensor='b', stage='corrected', processor='X')
        # No LatestEntry: last falls back to MAX.
        with timezone.override(None):
            span = coverage.monitor_span(self.monitor, 'pm10')
        assert span == {'first': date(2026, 2, 1), 'last': date(2026, 2, 3)}

    def test_endpoint_monitor_span(self):
        self.published_data()
        response, data = self.get(dataset='air-quality', entry_type='pm25', monitor=self.monitor.pk)
        assert response.status_code == 200
        assert data['data'] == {
            'dataset': 'air-quality', 'entry_type': 'pm25', 'monitor': str(self.monitor.pk),
            'first': '2026-01-01', 'last': '2026-01-01',
        }
        assert response['Cache-Control'] == 'public, max-age=900'

    def test_response_is_cached_server_side(self):
        params = {'dataset': 'air-quality', 'entry_type': 'pm25', 'monitor': self.monitor.pk}
        assert self.get(**params)[0]['X-Cache-Status'] == 'MISS'
        response, _ = self.get(**params)
        assert response['X-Cache-Status'] == 'HIT'
        assert response['Cache-Control'] == 'public, max-age=900'

    def test_monitor_with_no_data_returns_nulls(self):
        response, data = self.get(dataset='air-quality', entry_type='pm25', monitor=self.monitor.pk)
        assert response.status_code == 200
        assert data['data']['first'] is None
        assert data['data']['last'] is None

    def test_unknown_monitor_404(self):
        response, _ = self.get(dataset='air-quality', entry_type='pm25', monitor='AAAAAAAAAAAAAAAAAAAAAA')
        assert response.status_code == 404
        response, _ = self.get(dataset='air-quality', entry_type='pm25', monitor='not-an-id')
        assert response.status_code == 404

    def test_monitor_from_the_other_monitor_dataset_is_400(self):
        response, _ = self.get(dataset='weather', entry_type='temperature', monitor=self.monitor.pk)
        assert response.status_code == 400


class RegionSpanTests(CoverageTestCase):
    def test_region_span_reads_hourly_summaries_in_pacific_dates(self):
        make_region_summary(self.county, utc(2026, 3, 2, 7, 0))  # Mar 1 Pacific
        make_region_summary(self.county, utc(2026, 3, 5, 7, 0))  # Mar 4 Pacific
        make_region_summary(self.county, utc(2026, 1, 1, 8, 0), resolution='day')
        make_region_summary(self.county, utc(2026, 1, 1, 8, 0), entry_type='o3')
        with timezone.override(None):
            span = coverage.region_span(self.county, 'pm25')
        assert span == {'first': date(2026, 3, 1), 'last': date(2026, 3, 4)}

    def test_region_by_code_including_retired(self):
        make_region_summary(self.county, utc(2026, 3, 2, 7, 0))
        self.county.retire(date(2026, 6, 1))
        response, data = self.get(dataset='air-quality', entry_type='pm25', region_type='county', region='06019')
        assert response.status_code == 200
        assert data['data'] == {
            'dataset': 'air-quality', 'entry_type': 'pm25',
            'region': {'type': 'county', 'external_id': '06019'},
            'first': '2026-03-01', 'last': '2026-03-01',
        }

    def test_region_unknown_code_404(self):
        response, _ = self.get(dataset='air-quality', entry_type='pm25', region_type='county', region='99999')
        assert response.status_code == 404

    def test_land_use_region_400(self):
        response, _ = self.get(dataset='air-quality', entry_type='pm25', region_type='land_use', region='1')
        assert response.status_code == 400

    def test_unsummarized_entry_type_for_a_region_400(self):
        response, _ = self.get(dataset='air-quality', entry_type='pm10', region_type='county', region='06019')
        assert response.status_code == 400

    def test_region_with_weather_400(self):
        response, _ = self.get(dataset='weather', entry_type='temperature', region_type='county', region='06019')
        assert response.status_code == 400


class DatasetSpanTests(CoverageTestCase):
    def test_dataset_span_defaults_to_available_pollutants(self):
        make_monitor_summary(self.monitor, utc(2026, 3, 2, 7, 0))  # pm25, Mar 1 Pacific
        make_monitor_summary(self.monitor, utc(2026, 3, 6, 7, 0), entry_type='o3')  # Mar 5 Pacific
        make_monitor_summary(self.monitor, utc(2026, 2, 1, 12, 0), entry_type='no2')  # not available
        make_monitor_summary(self.monitor, utc(2026, 1, 1, 12, 0), resolution='day')  # not hourly
        with timezone.override(None):
            assert coverage.dataset_span('air-quality', None) == {'first': date(2026, 3, 1), 'last': date(2026, 3, 5)}
            assert coverage.dataset_span('air-quality', 'pm25') == {'first': date(2026, 3, 1), 'last': date(2026, 3, 1)}

    def test_dataset_level_pm10_is_400(self):
        response, data = self.get(dataset='air-quality', entry_type='pm10')
        assert response.status_code == 400
        assert data['error'] == 'pm10 has no dataset-level coverage; ask for a monitor.'

    def test_dataset_endpoint_shape(self):
        make_monitor_summary(self.monitor, utc(2026, 3, 2, 7, 0))
        response, data = self.get(dataset='air-quality')
        assert response.status_code == 200
        assert data['data'] == {'dataset': 'air-quality', 'entry_type': None, 'first': '2026-03-01', 'last': '2026-03-01'}

    def test_weather_span_reads_cimis_monitors(self):
        cimis = CIMIS.objects.create(
            name='CIMIS Station', station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326), location=CIMIS.LOCATION.outside,
        )
        make_entry(Humidity, cimis, utc(2026, 4, 1, 12, 0))
        make_entry(Temperature, cimis, utc(2026, 4, 2, 12, 0))
        latest = make_entry(Temperature, cimis, utc(2026, 4, 3, 12, 0))
        make_latest(cimis, latest)
        # A PurpleAir temperature is air-quality data, not weather.
        make_entry(Temperature, self.monitor, utc(2025, 1, 1, 12, 0), sensor='a')
        with timezone.override(None):
            assert coverage.dataset_span('weather', None) == {'first': date(2026, 4, 1), 'last': date(2026, 4, 3)}
            assert coverage.dataset_span('weather', 'temperature') == {'first': date(2026, 4, 2), 'last': date(2026, 4, 3)}

    def test_hms_fire_span(self):
        for day in (date(2026, 8, 1), date(2026, 8, 9)):
            Fire.objects.create(date=day, satellite='GOES-18', ecosystem=1, method='Auto', geometry=Point(-119.7, 36.7))
        assert coverage.dataset_span('hms-fire', None) == {'first': date(2026, 8, 1), 'last': date(2026, 8, 9)}

    def test_calenviroscreen_is_static(self):
        response, data = self.get(dataset='calenviroscreen')
        assert response.status_code == 200
        assert data['data']['first'] is None and data['data']['last'] is None

    def test_every_dataset_answers_when_empty(self):
        for dataset_id in catalog.DATASET_IDS:
            span = coverage.dataset_span(dataset_id, None)
            assert span == {'first': None, 'last': None}, dataset_id


class EmissionsSpanTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_facility_years_cover_whole_years(self):
        # emissions.yaml has inventory years 2023 and 2024.
        assert coverage.dataset_span('emissions', 'facility-nox') == {'first': date(2023, 1, 1), 'last': date(2024, 12, 31)}


class ValidationTests(CoverageTestCase):
    def test_unknown_dataset_400(self):
        assert self.get(dataset='nope')[0].status_code == 400
        assert self.get()[0].status_code == 400

    def test_unknown_entry_type_400(self):
        assert self.get(dataset='air-quality', entry_type='nope')[0].status_code == 400
        assert self.get(dataset='weather', entry_type='pm25')[0].status_code == 400

    def test_monitor_and_region_400(self):
        response, _ = self.get(
            dataset='air-quality', entry_type='pm25', monitor=self.monitor.pk,
            region_type='county', region='06019',
        )
        assert response.status_code == 400

    def test_place_without_entry_type_400(self):
        assert self.get(dataset='air-quality', monitor=self.monitor.pk)[0].status_code == 400
        assert self.get(dataset='air-quality', region_type='county', region='06019')[0].status_code == 400

    def test_place_with_non_monitor_dataset_400(self):
        response, _ = self.get(dataset='pesticide-use', entry_type='pounds-applied', region_type='county', region='06019')
        assert response.status_code == 400

    def test_region_needs_both_type_and_code(self):
        assert self.get(dataset='air-quality', entry_type='pm25', region='06019')[0].status_code == 400
        assert self.get(dataset='air-quality', entry_type='pm25', region_type='county')[0].status_code == 400
