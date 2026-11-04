import copy

from django.test import SimpleTestCase

from camp.utils.sentry import scrub_event

SECRET = '36.737,-119.787'


def frames():
    return {'frames': [{'function': 'post', 'vars': {'lat': SECRET}}]}


def event(url):
    return {
        'request': {
            'url': url,
            'method': 'POST',
            'query_string': 'lat=36.737&lon=-119.787',
            'data': {'lat': 36.737, 'lon': -119.787},
            'headers': {'Content-Type': 'application/json'},
        },
        'exception': {'values': [{'type': 'KeyError', 'stacktrace': frames()}]},
        'threads': {'values': [{'id': 1, 'stacktrace': frames()}]},
        'stacktrace': frames(),
    }


class ScrubEventTests(SimpleTestCase):
    def test_lookup_event_drops_body_query_and_vars(self):
        scrubbed = scrub_event(event('https://www.sjvair.com/api/2.0/regions/places/lookup/'), {})
        assert 'data' not in scrubbed['request']
        assert 'query_string' not in scrubbed['request']
        assert scrubbed['request']['method'] == 'POST'
        assert SECRET not in repr(scrubbed)
        assert 'lat=36' not in repr(scrubbed)

    def test_documents_event_still_scrubbed(self):
        scrubbed = scrub_event(event('https://www.sjvair.com/api/2.0/documents/doc/'), {})
        assert 'data' not in scrubbed['request']
        assert SECRET not in repr(scrubbed)

    def test_other_event_untouched(self):
        original = event('https://www.sjvair.com/api/2.0/monitors/')
        assert scrub_event(copy.deepcopy(original), {}) == original
