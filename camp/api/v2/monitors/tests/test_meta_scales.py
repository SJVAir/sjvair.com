import json

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

    def test_levels_key_removed(self):
        entries = self._fetch_entries()
        assert all('levels' not in e for e in entries.values())

    def test_school_guidelines_pm25_only(self):
        entries = self._fetch_entries()
        block = entries['pm25']['school_guidelines']
        assert block['resolution'] == 'hour'
        assert block['label'] == 'Outdoor Activity Guidelines for Schools'
        assert block['source'] == {'name': 'SJVAir', 'url': 'http://testserver/guidelines/schools/'}
        assert [a['key'] for a in block['activities']] == ['recess', 'pe', 'athletics', 'events']
        assert block['activities'][0]['levels']['good'] == ['No restrictions.']
        assert block['activities'][3]['duration'] is None
        for key, entry in entries.items():
            if key != 'pm25':
                assert entry['school_guidelines'] is None, key

    def test_school_guidelines_plain_strings(self):
        block = self._fetch_entries()['pm25']['school_guidelines']

        def leaves(node):
            if isinstance(node, dict):
                for v in node.values():
                    yield from leaves(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    yield from leaves(v)
            else:
                yield node

        assert all(type(v) is str or v is None for v in leaves(block))
        json.dumps(block)

    def test_scale_null_without_levels(self):
        assert self._fetch_entries()['humidity']['scale'] is None
