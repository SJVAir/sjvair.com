import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.monitors import endpoints
from camp.utils.test import get_response_data

monitor_meta = endpoints.MonitorMetaEndpoint.as_view()


class MonitorMetaLabelTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def _fetch(self):
        url = reverse('api:v2:monitors:monitor-meta')
        return get_response_data(monitor_meta(RequestFactory().get(url)))['data']

    def test_stages_listed(self):
        stages = self._fetch()['stages']
        assert set(stages) == {'raw', 'corrected', 'cleaned', 'calibrated'}
        for key, stage in stages.items():
            assert stage['key'] == key
            assert stage['label']
            assert stage['description']

    def test_processors_listed(self):
        data = self._fetch()
        assert 'PM25_EPA_Oct2021' in data['processors']
        for monitor in data['monitors'].values():
            for entry in monitor['entries'].values():
                for names in entry['processors'].values():
                    for name in names:
                        assert name in data['processors']

    def test_every_processor_has_label(self):
        for key, proc in self._fetch()['processors'].items():
            assert proc['key'] == key
            assert proc['label'] != key
            assert proc['description']


class MonitorMetaAlertsTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def _fetch(self):
        url = reverse('api:v2:monitors:monitor-meta')
        return get_response_data(monitor_meta(RequestFactory().get(url)))['data']

    def _entry(self, monitor_type, entry_type):
        monitors = self._fetch()['monitors']
        if monitor_type not in monitors:
            pytest.skip(f'{monitor_type} is not enabled')
        return monitors[monitor_type]['entries'][entry_type]

    def test_purpleair_pm25_alerts(self):
        assert self._entry('purpleair', 'pm25')['alerts'] == {
            'window': '60 min',
            'min_coverage': 0.5,
            'stage': 'calibrated',
            'processor': 'PM25_UnivariateLinearRegression',
            'expected_interval': None,
        }

    def test_aqlite_o3_override(self):
        alerts = self._entry('aqlite', 'o3')['alerts']
        assert alerts['stage'] == 'calibrated'
        assert alerts['processor'] is None
        assert alerts['expected_interval'] == '1h'

    def test_airnow_o3_no_processor(self):
        alerts = self._entry('airnow', 'o3')['alerts']
        assert alerts['stage'] == 'raw'
        assert alerts['processor'] is None

    def test_non_alertable_is_null(self):
        assert self._entry('purpleair', 'pm100')['alerts'] is None

    def test_every_entry_has_alerts_key(self):
        for monitor in self._fetch()['monitors'].values():
            for entry in monitor['entries'].values():
                assert 'alerts' in entry
