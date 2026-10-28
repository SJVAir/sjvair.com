import copy

from django.test import SimpleTestCase

from camp.apps.documents.sentry import scrub_documents

SECRET = 'PRIVATE-MARKER-7f3a9c'


def frames():
    return {'frames': [
        {'function': 'put', 'vars': {'body': SECRET}},
        {'function': 'save_locked', 'vars': {'cleaned': {'name': SECRET}}},
    ]}


def event(url):
    return {
        'request': {
            'url': url,
            'method': 'PUT',
            'query_string': '',
            'data': {'body': {'note': SECRET}, 'name': SECRET},
            'headers': {'Content-Type': 'application/json'},
        },
        'exception': {'values': [{'type': 'KeyError', 'stacktrace': frames()}]},
        'threads': {'values': [{'id': 1, 'stacktrace': frames()}]},
        'stacktrace': frames(),
    }


class ScrubDocumentsTests(SimpleTestCase):
    def test_documents_request_loses_data_and_frame_vars(self):
        for url in (
            'https://www.sjvair.com/api/2.0/documents/doc/',
            'http://localhost:8000/api/2.0/documents/',
            'https://www.sjvair.com/api/2.0/documents/shared/tok/changes/',
        ):
            with self.subTest(url=url):
                scrubbed = scrub_documents(event(url), {})
                self.assertNotIn(SECRET, repr(scrubbed))
                self.assertNotIn('data', scrubbed['request'])
                self.assertEqual(scrubbed['request']['method'], 'PUT')
                self.assertEqual(scrubbed['request']['url'], url)
                frame = scrubbed['exception']['values'][0]['stacktrace']['frames'][0]
                self.assertEqual(frame, {'function': 'put'})

    def test_other_requests_untouched(self):
        for url in (
            'https://www.sjvair.com/api/2.0/monitors/',
            'https://www.sjvair.com/account/documents/',
            'https://www.sjvair.com/workspace/api/2.0/documents/',
        ):
            with self.subTest(url=url):
                original = event(url)
                self.assertEqual(scrub_documents(copy.deepcopy(original), {}), original)

    def test_events_without_a_request_untouched(self):
        original = {'message': 'task failed', 'stacktrace': frames()}
        self.assertEqual(scrub_documents(copy.deepcopy(original), {}), original)
