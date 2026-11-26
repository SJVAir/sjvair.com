import copy
import json

from django.test import SimpleTestCase

from camp.utils.sentry import is_lookup_path, scrub_event

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

    def test_lookup_event_drops_exception_messages_and_breadcrumbs(self):
        e = event('https://www.sjvair.com/api/2.0/regions/places/lookup/')
        e['exception']['values'][0]['value'] = "bad point (36.737, -119.787)"
        e['breadcrumbs'] = {'values': [{'message': 'POST lat=36.737'}]}
        scrubbed = scrub_event(e, {})
        assert 'value' not in scrubbed['exception']['values'][0]
        assert 'breadcrumbs' not in scrubbed

    def test_lookup_url_query_is_stripped(self):
        e = event('https://www.sjvair.com/api/2.0/regions/places/lookup/?lat=36.737&lon=-119.787')
        scrubbed = scrub_event(e, {})
        dumped = json.dumps(scrubbed)
        assert '36.737' not in dumped and '119.787' not in dumped
        assert scrubbed['request']['url'] == 'https://www.sjvair.com/api/2.0/regions/places/lookup/'

    def test_documents_event_still_scrubbed(self):
        scrubbed = scrub_event(event('https://www.sjvair.com/api/2.0/documents/doc/'), {})
        assert 'data' not in scrubbed['request']
        assert SECRET not in repr(scrubbed)

    def test_other_event_untouched(self):
        original = event('https://www.sjvair.com/api/2.0/monitors/')
        assert scrub_event(copy.deepcopy(original), {}) == original

    def test_lookup_path_without_trailing_slash_is_scrubbed(self):
        scrubbed = scrub_event(event('https://www.sjvair.com/api/2.0/regions/places/lookup?lat=36.737'), {})
        assert 'data' not in scrubbed['request']
        assert SECRET not in repr(scrubbed)


class LookupPathTests(SimpleTestCase):

    def test_matches_with_and_without_trailing_slash(self):
        assert is_lookup_path('/api/2.0/regions/places/lookup/')
        assert is_lookup_path('/api/2.0/regions/places/lookup')

    def test_other_paths_do_not_match(self):
        assert not is_lookup_path('/api/2.0/regions/places/')
        assert not is_lookup_path('/api/2.0/regions/places/lookups/')
