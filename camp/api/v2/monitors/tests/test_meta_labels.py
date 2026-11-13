import pytest

from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.monitors import endpoints
from camp.apps.monitors.models import Monitor
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


class MonitorMetaGroupTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def _fetch(self):
        url = reverse('api:v2:monitors:monitor-meta')
        return get_response_data(monitor_meta(RequestFactory().get(url)))['data']

    def test_monitor_groups(self):
        assert self._fetch()['monitor_groups'] == {
            'reference': {'key': 'reference', 'label': 'Reference-grade', 'order': 0},
            'low-cost': {'key': 'low-cost', 'label': 'Low-cost sensors', 'order': 1},
        }

    def test_group_labels_are_plain_strings(self):
        for group in self._fetch()['monitor_groups'].values():
            assert type(group['label']) is str

    def test_every_graded_type_has_a_group(self):
        data = self._fetch()
        for monitor_model in Monitor.get_enabled_subclasses():
            if monitor_model.GRADE is not None:
                assert data['monitors'][monitor_model.monitor_type]['group'] in data['monitor_groups']

    def test_gradeless_type_listed_with_null_group(self):
        # Empty MONITOR_ENABLED_TYPES enables every type, CIMIS (GRADE None) included.
        with self.settings(MONITOR_ENABLED_TYPES=[]):
            monitors = self._fetch()['monitors']
        assert 'cimis' in monitors
        assert monitors['cimis']['group'] is None

    def test_current_type_groups(self):
        monitors = self._fetch()['monitors']
        expected = {
            'airnow': 'reference', 'aqlite': 'reference', 'aqview': 'reference', 'bam1022': 'reference',
            'airgradient': 'low-cost', 'purpleair': 'low-cost', 'vozbox': 'low-cost',
        }
        for monitor_type, group in expected.items():
            if monitor_type in monitors:
                assert monitors[monitor_type]['group'] == group

    def test_bam1022_label_unchanged(self):
        monitors = self._fetch()['monitors']
        if 'bam1022' in monitors:
            assert monitors['bam1022']['label'] == 'BAM 1022'


class GradeGroupMappingTests(TestCase):
    def test_grade_mapping(self):
        cases = {
            Monitor.Grade.FEM: Monitor.GradeGroup.REFERENCE,
            Monitor.Grade.FRM: Monitor.GradeGroup.REFERENCE,
            Monitor.Grade.LCS: Monitor.GradeGroup.LOW_COST,
            None: None,
        }
        for grade, group in cases.items():
            with patch.object(Monitor, 'GRADE', grade):
                assert Monitor.get_grade_group() == group
