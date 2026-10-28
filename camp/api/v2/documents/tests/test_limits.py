from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from camp.apps.documents.models import DocumentChange, SavedDocument, measure

from .helpers import body, make_user, save


def code(response):
    return response.json()['errors']['detail'][0]['code']


class LimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user(1)
        self.client = Client()
        self.client.force_login(self.alice)

    def put(self, id, **overrides):
        return save(self.client, id, **overrides)

    def fill(self, count, **overrides):
        for i in range(count):
            self.assertEqual(self.put(f'd{i}', **overrides).status_code, 200)

    def test_fifty_live_then_refused(self):
        self.fill(50)
        response = self.put('extra')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(code(response), 'limit_documents')
        self.assertEqual(response.json()['data'], {'limit': 50})
        self.assertFalse(SavedDocument.objects.filter(pk='extra').exists())
        # saving an existing one still works
        self.assertEqual(self.put('d0', base_version=1).status_code, 200)

    def test_deleted_dont_count_toward_fifty(self):
        self.fill(49)
        self.assertEqual(self.put('trash', deleted_at='2026-01-01T00:00:00Z').status_code, 200)
        self.assertEqual(self.put('fiftieth').status_code, 200)
        self.assertEqual(code(self.put('fifty-first')), 'limit_documents')

    def test_undelete_at_fifty_refused(self):
        self.assertEqual(self.put('trash', deleted_at='2026-01-01T00:00:00Z').status_code, 200)
        self.fill(50)
        response = self.put('trash', base_version=1, deleted_at=None)
        self.assertEqual(code(response), 'limit_documents')
        self.assertIsNotNone(SavedDocument.objects.get(pk='trash').deleted_at)

    def test_creating_deleted_at_fifty_allowed(self):
        self.fill(50)
        response = self.put('trash', deleted_at='2026-01-01T00:00:00Z')
        self.assertEqual(response.status_code, 200)

    @override_settings(DOCUMENTS_MAX_STORAGE=1000)
    def test_storage_limit_counts_deleted(self):
        size = measure(body())
        pad = {'text': 'x' * (400 - measure({'text': ''}))}
        self.assertEqual(self.put('a', body=pad).status_code, 200)
        self.assertEqual(self.put('b', body=pad, deleted_at='2026-01-01T00:00:00Z').status_code, 200)
        response = self.put('c', body={'text': 'x' * (300 - measure({'text': ''}))})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(code(response), 'limit_storage')
        self.assertEqual(response.json()['data'], {'limit': 1000})
        self.assertFalse(SavedDocument.objects.filter(pk='c').exists())
        # replacing a doc's own body subtracts its old size
        self.assertEqual(self.put('a', base_version=1, body=pad).status_code, 200)
        self.assertGreater(size, 0)

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=3)
    def test_rate_limit_121st_save(self):
        for i in range(3):
            self.assertEqual(self.put(f'r{i}').status_code, 200)
        before = SavedDocument.objects.count(), DocumentChange.objects.count()
        response = self.put('r3')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(code(response), 'rate_limited')
        self.assertEqual((SavedDocument.objects.count(), DocumentChange.objects.count()), before)

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=1)
    def test_rate_limit_is_per_account(self):
        self.assertEqual(self.put('a').status_code, 200)
        other = Client()
        other.force_login(make_user(2))
        self.assertEqual(save(other, 'b').status_code, 200)
