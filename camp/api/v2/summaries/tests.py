from datetime import datetime, timedelta
from unittest import mock

import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.summaries.endpoints import BulkMonitorSummaryList, MonitorSummaryList, RegionSummaryList
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.utils.test import get_response_data

monitor_summary_list = MonitorSummaryList.as_view()
region_summary_list = RegionSummaryList.as_view()
bulk_monitor_summary_list = BulkMonitorSummaryList.as_view()

pytestmark = [
    pytest.mark.usefixtures('purpleair_monitor'),
    pytest.mark.django_db(transaction=True),
]

# Minimal stats for creating test records
STATS = {
    'count': 30,
    'expected_count': 30,
    'sum_value': 300.0,
    'sum_of_squares': 3000.0,
    'minimum': 10.0,
    'maximum': 10.0,
    'mean': 10.0,
    'stddev': 0.0,
    'p25': 10.0,
    'p75': 10.0,
    'tdigest': {'C': [], 'n': 0},
}


def make_monitor_summary(monitor, timestamp, resolution='hour', entry_type='pm25', processor=''):
    return MonitorSummary.objects.create(
        monitor=monitor,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        processor=processor,
        is_complete=True,
        **STATS,
    )


def make_region_summary(region, timestamp, resolution='hour', entry_type='pm25'):
    return RegionSummary.objects.create(
        region=region,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        station_count=3,
        weight=30.0,
        **STATS,
    )


class MonitorSummaryListTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.first()
        self.hour = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        make_monitor_summary(self.monitor, self.hour)

    def _get(self, url_name, entry_type, resolution, year=None, month=None, day=None, query=None):
        """
        Call the monitor summary list view directly.
        resolution: passed to the view directly (not in reverse() kwargs — not a URL capture group)
        year/month/day: included in both reverse() kwargs and view kwargs
        """
        reverse_kwargs = {'monitor_id': self.monitor.pk, 'entry_type': entry_type}
        view_kwargs = {'monitor_id': self.monitor.pk, 'entry_type': entry_type, 'resolution': resolution}
        if year is not None:
            reverse_kwargs['year'] = year
            view_kwargs['year'] = year
        if month is not None:
            reverse_kwargs['month'] = month
            view_kwargs['month'] = month
        if day is not None:
            reverse_kwargs['day'] = day
            view_kwargs['day'] = day

        url = reverse(f'api:v2:monitors:{url_name}', kwargs=reverse_kwargs)
        request = self.factory.get(url, query or {})
        request.monitor = self.monitor
        return monitor_summary_list(request, **view_kwargs)

    def test_hourly_year_returns_200(self):
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        assert response.status_code == 200

    def test_year_filter_isolates_records(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2025, 3, 15, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_response_fields_no_machinery(self):
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        record = data['data'][0]
        assert 'sum_value' not in record
        assert 'sum_of_squares' not in record
        assert 'tdigest' not in record
        assert 'mean' in record
        assert 'p25' in record
        assert 'p75' in record
        assert 'processor' in record
        assert 'resolution' in record
        assert 'is_complete' in record

    def test_missing_monitor_returns_404(self):
        url = reverse('api:v2:monitors:monitor-summary-hourly-year', kwargs={
            'monitor_id': self.monitor.pk,
            'entry_type': 'pm25',
            'year': 2026,
        })
        request = self.factory.get(url)
        request.monitor = None
        response = monitor_summary_list(request, monitor_id=self.monitor.pk, entry_type='pm25', resolution='hour', year=2026)
        assert response.status_code == 404

    def test_processor_filter_default_empty_string(self):
        make_monitor_summary(self.monitor, self.hour, processor='PM25_EPA_Oct2021')
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        # Default processor='' returns only raw record
        assert len(data['data']) == 1
        assert data['data'][0]['processor'] == ''

    def test_processor_filter_explicit(self):
        make_monitor_summary(self.monitor, self.hour, processor='PM25_EPA_Oct2021')
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026, query={'processor': 'PM25_EPA_Oct2021'})
        data = get_response_data(response)
        assert len(data['data']) == 1
        assert data['data'][0]['processor'] == 'PM25_EPA_Oct2021'

    def test_invalid_entry_type_returns_404(self):
        response = self._get('monitor-summary-hourly-year', 'badtype', 'hour', year=2026)
        assert response.status_code == 404

    def test_ordered_by_timestamp_ascending(self):
        for i in range(1, 4):
            make_monitor_summary(self.monitor, self.hour + timedelta(hours=i))
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        timestamps = [r['timestamp'] for r in data['data']]
        assert timestamps == sorted(timestamps)

    def test_yearly_no_date_returns_all(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2025, 1, 1)), resolution='year')
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 1, 1)), resolution='year')
        url = reverse('api:v2:monitors:monitor-summary-yearly', kwargs={
            'monitor_id': self.monitor.pk,
            'entry_type': 'pm25',
        })
        request = self.factory.get(url)
        request.monitor = self.monitor
        response = monitor_summary_list(request, monitor_id=self.monitor.pk, entry_type='pm25', resolution='year')
        data = get_response_data(response)
        assert len(data['data']) == 2

    def test_month_filter(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 4, 15, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-month', 'pm25', 'hour', year=2026, month=3)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_day_filter(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 3, 16, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-day', 'pm25', 'hour', year=2026, month=3, day=15)
        data = get_response_data(response)
        assert len(data['data']) == 1


class BulkMonitorSummaryListTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.purpleair = PurpleAir.objects.get(sensor_id=8892)
        self.bam = BAM1022.objects.get(pk='gO9_akFVTVW6mYBifOtoxg')
        self.day = timezone.make_aware(datetime(2026, 3, 15, 0, 0, 0))
        # Each monitor's published series: EPA-calibrated for PurpleAir, raw for
        # the BAM (its default processor emits CLEANED, which isn't summarized).
        make_monitor_summary(self.purpleair, self.day, resolution='day', processor='PM25_EPA_Oct2021')
        make_monitor_summary(self.bam, self.day, resolution='day')
        self.march = {'start': '2026-03-01', 'end': '2026-03-31'}

    def _get(self, entry_type='pm25', resolution='day', query=None, url_name='monitor-summary-bulk-daily'):
        kwargs = {'entry_type': entry_type}
        url = reverse(f'api:v2:monitors:{url_name}', kwargs=kwargs)
        request = self.factory.get(url, query or {})
        return bulk_monitor_summary_list(request, entry_type=entry_type, resolution=resolution)

    def _rows(self, data):
        return sum(len(r['summaries']) for r in data['data'])

    def test_url_lives_beside_the_other_entry_type_endpoints(self):
        url = reverse('api:v2:monitors:monitor-summary-bulk-daily', kwargs={'entry_type': 'pm25'})
        assert url.endswith('/monitors/pm25/summaries/daily/')

    def test_returns_200(self):
        response = self._get(query=self.march)
        assert response.status_code == 200

    def test_missing_date_range_returns_400(self):
        response = self._get()
        assert response.status_code == 400
        errors = get_response_data(response)['errors']
        assert 'start' in errors
        assert 'end' in errors

    def test_start_after_end_returns_400(self):
        response = self._get(query={'start': '2026-03-31', 'end': '2026-03-01'})
        assert response.status_code == 400

    def test_invalid_bbox_returns_400(self):
        response = self._get(query={**self.march, 'bbox': 'not-a-bbox'})
        assert response.status_code == 400
        assert 'bbox' in get_response_data(response)['errors']

    def test_far_future_end_returns_400_not_500(self):
        response = self._get(query={'start': '2026-01-01', 'end': '9999-12-31'})
        assert response.status_code == 400

    def test_hourly_range_is_capped(self):
        response = self._get(resolution='hour', url_name='monitor-summary-bulk-hourly', query={
            'start': '2026-01-01', 'end': '2026-02-15',
        })
        assert response.status_code == 400

        response = self._get(resolution='hour', url_name='monitor-summary-bulk-hourly', query={
            'start': '2026-01-01', 'end': '2026-01-31',
        })
        assert response.status_code == 200

    def test_daily_range_is_capped(self):
        response = self._get(query={'start': '2025-01-01', 'end': '2026-03-31'})
        assert response.status_code == 400

    def test_coarse_resolutions_are_not_capped(self):
        response = self._get(resolution='month', url_name='monitor-summary-bulk-monthly', query={
            'start': '2000-01-01', 'end': '2026-12-31',
        })
        assert response.status_code == 200

    def test_results_are_monitors_with_nested_summaries(self):
        response = self._get(query=self.march)
        data = get_response_data(response)
        result = next(r for r in data['data'] if r['id'] == str(self.purpleair.pk))
        # Same shape as MonitorSerializer (id, name, position, ...) plus nested summaries.
        assert result['name'] == self.purpleair.name
        assert 'position' in result
        assert len(result['summaries']) == 1
        assert result['summaries'][0]['mean'] == 10.0
        assert 'monitor' not in result['summaries'][0]

    def test_includes_summaries_from_multiple_monitors(self):
        response = self._get(query=self.march)
        data = get_response_data(response)
        monitor_ids = {r['id'] for r in data['data']}
        assert monitor_ids == {str(self.purpleair.pk), str(self.bam.pk)}

    def test_default_processor_is_each_monitor_types_published_series(self):
        # Raw PurpleAir rows exist too, but the map publishes the EPA
        # calibration for PurpleAir, so that's what comes back by default.
        make_monitor_summary(self.purpleair, self.day, resolution='day', processor='')
        response = self._get(query=self.march)
        data = get_response_data(response)
        by_id = {r['id']: r for r in data['data']}
        assert [s['processor'] for s in by_id[str(self.purpleair.pk)]['summaries']] == ['PM25_EPA_Oct2021']
        assert [s['processor'] for s in by_id[str(self.bam.pk)]['summaries']] == ['']

    def test_explicit_processor_is_an_exact_match_across_monitors(self):
        make_monitor_summary(self.purpleair, self.day, resolution='day', processor='')

        response = self._get(query={**self.march, 'processor': 'PM25_EPA_Oct2021'})
        data = get_response_data(response)
        assert {r['id'] for r in data['data']} == {str(self.purpleair.pk)}

        response = self._get(query={**self.march, 'processor': ''})
        data = get_response_data(response)
        by_id = {r['id']: r for r in data['data']}
        assert set(by_id) == {str(self.purpleair.pk), str(self.bam.pk)}
        assert [s['processor'] for s in by_id[str(self.purpleair.pk)]['summaries']] == ['']

    def test_date_range_excludes_records_outside_it(self):
        make_monitor_summary(self.purpleair, timezone.make_aware(datetime(2026, 4, 1)), resolution='day', processor='PM25_EPA_Oct2021')
        response = self._get(query=self.march)
        assert self._rows(get_response_data(response)) == 2

    def test_date_range_is_inclusive_of_end_date(self):
        make_monitor_summary(self.purpleair, timezone.make_aware(datetime(2026, 3, 31)), resolution='day', processor='PM25_EPA_Oct2021')
        response = self._get(query=self.march)
        assert self._rows(get_response_data(response)) == 3

    def _move_bam_away(self):
        # bam1022.yaml fixture places the BAM at the same coordinates as the
        # PurpleAir - move it away so spatial scoping actually distinguishes them.
        from django.contrib.gis.geos import Point
        self.bam.position = Point(self.bam.position.x + 10, self.bam.position.y + 10, srid=4326)
        self.bam.save()

    def test_filters_by_bbox(self):
        self._move_bam_away()
        lon, lat = self.purpleair.position.x, self.purpleair.position.y
        response = self._get(query={
            **self.march,
            'bbox': f'{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}',
        })
        data = get_response_data(response)
        assert {r['id'] for r in data['data']} == {str(self.purpleair.pk)}

    def test_filters_by_region(self):
        from django.contrib.gis.geos import MultiPolygon, Polygon
        from camp.apps.regions.models import Boundary

        self._move_bam_away()
        lon, lat = self.purpleair.position.x, self.purpleair.position.y
        region = Region.objects.create(name='Test', slug='test', type=Region.Type.COUNTY)
        boundary = Boundary.objects.create(
            region=region, version='test',
            geometry=MultiPolygon(Polygon.from_bbox((lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01))),
        )
        region.boundary = boundary
        region.save()

        response = self._get(query={**self.march, 'region': region.sqid})
        data = get_response_data(response)
        assert {r['id'] for r in data['data']} == {str(self.purpleair.pk)}

    def test_bad_region_id_404s(self):
        response = self._get(query={**self.march, 'region': 'not-a-real-sqid'})
        assert response.status_code == 404

    def test_invalid_entry_type_returns_404(self):
        response = self._get(entry_type='badtype', query=self.march)
        assert response.status_code == 404

    def test_excludes_monitors_without_a_position(self):
        # Parity with current/ and at/: unscoped and scoped requests should
        # agree on which monitors exist.
        self.bam.position = None
        self.bam.save()
        response = self._get(query=self.march)
        data = get_response_data(response)
        assert {r['id'] for r in data['data']} == {str(self.purpleair.pk)}

    def test_ordered_by_timestamp_within_monitor(self):
        make_monitor_summary(self.purpleair, self.day + timedelta(days=1), resolution='day', processor='PM25_EPA_Oct2021')
        response = self._get(query=self.march)
        data = get_response_data(response)
        result = next(r for r in data['data'] if r['id'] == str(self.purpleair.pk))
        timestamps = [row['timestamp'] for row in result['summaries']]
        assert timestamps == sorted(timestamps)

    def test_pages_are_ordered_by_monitor_id_not_name(self):
        # Monitor.Meta.ordering is by name, which isn't unique. Two monitors
        # with the same name must still come back as contiguous runs of rows.
        self.bam.name = self.purpleair.name
        self.bam.save()
        make_monitor_summary(self.purpleair, self.day + timedelta(days=1), resolution='day', processor='PM25_EPA_Oct2021')
        make_monitor_summary(self.bam, self.day + timedelta(days=1), resolution='day')

        expected = sorted([str(self.purpleair.pk), str(self.bam.pk)])
        seen = []
        with mock.patch.object(BulkMonitorSummaryList, 'page_size', 1):
            for page in range(1, 5):
                data = get_response_data(self._get(query={**self.march, 'page': page}))['data']
                assert len(data) == 1
                seen.append(data[0]['id'])

        assert seen == [expected[0], expected[0], expected[1], expected[1]]

    def test_monitor_split_across_pages_is_detectable(self):
        # purpleair gets a second row so it has more rows than fit on a
        # page of size 1 - it should show up (partially) on both pages,
        # under the same `id`, so a client can detect and merge the split
        # per the endpoint's docstring.
        make_monitor_summary(self.purpleair, self.day + timedelta(days=1), resolution='day', processor='PM25_EPA_Oct2021')

        # Rows are ordered by monitor id, then timestamp - find which pages
        # purpleair's two rows land on.
        first = 2 if str(self.bam.pk) < str(self.purpleair.pk) else 1
        with mock.patch.object(BulkMonitorSummaryList, 'page_size', 1):
            page_a = self._get(query={**self.march, 'page': first})
            page_b = self._get(query={**self.march, 'page': first + 1})

        page_a_data = get_response_data(page_a)['data']
        page_b_data = get_response_data(page_b)['data']

        assert len(page_a_data) == 1
        assert len(page_b_data) == 1
        assert page_a_data[0]['id'] == page_b_data[0]['id'] == str(self.purpleair.pk)
        assert len(page_a_data[0]['summaries']) == 1
        assert len(page_b_data[0]['summaries']) == 1

    def test_monitor_related_data_is_not_loaded_per_monitor(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = self._get(query=self.march)
        assert response.status_code == 200
        health_queries = [q['sql'] for q in ctx.captured_queries if 'qaqc_healthcheck' in q['sql']]
        # One JOIN via select_related, never one SELECT per monitor.
        assert not any(sql.strip().upper().startswith('SELECT') and 'JOIN' not in sql.upper() for sql in health_queries)


class RegionSummaryListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.hour = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        make_region_summary(self.region, self.hour)

    def _get(self, url_name, entry_type, resolution, year=None, month=None, day=None, query=None):
        reverse_kwargs = {'region_id': self.region.sqid, 'entry_type': entry_type}
        view_kwargs = {'region_id': self.region.sqid, 'entry_type': entry_type, 'resolution': resolution}
        if year is not None:
            reverse_kwargs['year'] = year
            view_kwargs['year'] = year
        if month is not None:
            reverse_kwargs['month'] = month
            view_kwargs['month'] = month
        if day is not None:
            reverse_kwargs['day'] = day
            view_kwargs['day'] = day

        url = reverse(f'api:v2:regions:{url_name}', kwargs=reverse_kwargs)
        request = self.factory.get(url, query or {})
        return region_summary_list(request, **view_kwargs)

    def test_hourly_year_returns_200(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        assert response.status_code == 200

    def test_response_has_station_count(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert 'station_count' in data['data'][0]

    def test_response_has_no_processor(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert 'processor' not in data['data'][0]

    def test_response_fields_no_machinery(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        record = data['data'][0]
        assert 'sum_value' not in record
        assert 'tdigest' not in record
        assert 'weight' not in record
        assert 'is_complete' not in record
        assert 'resolution' in record

    def test_invalid_region_returns_404(self):
        request = self.factory.get('/')
        response = region_summary_list(request, region_id='doesnotexist', entry_type='pm25', resolution='hour', year=2026)
        assert response.status_code == 404

    def test_year_filter_isolates_records(self):
        make_region_summary(self.region, timezone.make_aware(datetime(2025, 3, 15, 10, 0, 0)))
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_ordered_by_timestamp_ascending(self):
        for i in range(1, 4):
            make_region_summary(self.region, self.hour + timedelta(hours=i))
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        timestamps = [r['timestamp'] for r in data['data']]
        assert timestamps == sorted(timestamps)

    def test_month_filter(self):
        # setUp creates a record in March 2026; add one in April — month=3 should exclude it.
        make_region_summary(self.region, timezone.make_aware(datetime(2026, 4, 15, 10, 0, 0)))
        response = self._get('region-summary-hourly-month', 'pm25', 'hour', year=2026, month=3)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_day_filter(self):
        # setUp creates a record on March 15; add one on March 16 — day=15 should exclude it.
        make_region_summary(self.region, timezone.make_aware(datetime(2026, 3, 16, 10, 0, 0)))
        response = self._get('region-summary-hourly-day', 'pm25', 'hour', year=2026, month=3, day=15)
        data = get_response_data(response)
        assert len(data['data']) == 1
