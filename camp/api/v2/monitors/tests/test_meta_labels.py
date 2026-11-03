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
