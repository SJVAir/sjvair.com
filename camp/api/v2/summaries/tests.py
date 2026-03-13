from datetime import datetime, timedelta

import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.summaries.endpoints import MonitorSummaryList, RegionSummaryList
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.utils.test import get_response_data

monitor_summary_list = MonitorSummaryList.as_view()
region_summary_list = RegionSummaryList.as_view()

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
    'is_complete': True,
    'tdigest': {'C': [], 'n': 0},
}


def make_monitor_summary(monitor, timestamp, resolution='hour', entry_type='pm25', processor=''):
    return MonitorSummary.objects.create(
        monitor=monitor,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        processor=processor,
        **STATS,
    )


def make_region_summary(region, timestamp, resolution='hour', entry_type='pm25'):
    return RegionSummary.objects.create(
        region=region,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        station_count=3,
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
        assert 'is_complete' in record

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


class RegionSummaryListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.hour = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        make_region_summary(self.region, self.hour)

    def _get(self, url_name, entry_type, resolution, year=None, month=None, day=None, query=None):
        reverse_kwargs = {'region_id': self.region.pk, 'entry_type': entry_type}
        view_kwargs = {'region_id': self.region.pk, 'entry_type': entry_type, 'resolution': resolution}
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
