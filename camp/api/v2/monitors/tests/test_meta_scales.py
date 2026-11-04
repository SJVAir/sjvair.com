from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.monitors import endpoints
from camp.utils.test import get_response_data

monitor_meta = endpoints.MonitorMetaEndpoint.as_view()


class MonitorMetaScaleTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def _fetch_entries(self):
        url = reverse('api:v2:monitors:monitor-meta')
        return get_response_data(monitor_meta(RequestFactory().get(url)))['data']['entries']

    def test_pm25_scale_present(self):
        scale = self._fetch_entries()['pm25']['scale']
        assert scale['id'] == 'pm25'
        assert len(scale['levels']) == 6
        assert scale['levels'][0]['tier'] == 0

    def test_levels_dict_unchanged(self):
        levels = self._fetch_entries()['pm25']['levels']
        assert set(levels['GOOD'].keys()) == {'name', 'label', 'color', 'range', 'guidance', 'tier'}

    def test_scale_null_without_levels(self):
        assert self._fetch_entries()['humidity']['scale'] is None
