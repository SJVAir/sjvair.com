from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from camp.apps.documents.models import DocumentChange, SavedDocument, measure

from .. import save as save_module
from .helpers import START_OF_MINUTE, body, frozen_clock, make_user, save


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
            assert self.put(f'd{i}', **overrides).status_code == 200

    def test_fifty_live_then_refused(self):
        self.fill(50)
        response = self.put('extra')
        assert response.status_code == 403
        assert code(response) == 'limit_documents'
        assert response.json()['data'] == {'limit': 50}
        assert not SavedDocument.objects.filter(pk='extra').exists()
        # saving an existing one still works
        assert self.put('d0', base_version=1).status_code == 200

    def test_deleted_dont_count_toward_fifty(self):
        self.fill(49)
        assert self.put('trash', deleted_at='2026-01-01T00:00:00Z').status_code == 200
        assert self.put('fiftieth').status_code == 200
        assert code(self.put('fifty-first')) == 'limit_documents'

    def test_undelete_at_fifty_refused(self):
        assert self.put('trash', deleted_at='2026-01-01T00:00:00Z').status_code == 200
        self.fill(50)
        response = self.put('trash', base_version=1, deleted_at=None)
        assert code(response) == 'limit_documents'
        assert SavedDocument.objects.get(pk='trash').deleted_at is not None

    def test_creating_deleted_at_fifty_allowed(self):
        self.fill(50)
        response = self.put('trash', deleted_at='2026-01-01T00:00:00Z')
        assert response.status_code == 200

    @override_settings(DOCUMENTS_MAX_STORAGE=1000)
    def test_storage_limit_counts_deleted(self):
        size = measure(body())
        pad = {'text': 'x' * (400 - measure({'text': ''}))}
        assert self.put('a', body=pad).status_code == 200
        assert self.put('b', body=pad, deleted_at='2026-01-01T00:00:00Z').status_code == 200
        response = self.put('c', body={'text': 'x' * (300 - measure({'text': ''}))})
        assert response.status_code == 403
        assert code(response) == 'limit_storage'
        assert response.json()['data'] == {'limit': 1000}
        assert not SavedDocument.objects.filter(pk='c').exists()
        # replacing a doc's own body subtracts its old size
        assert self.put('a', base_version=1, body=pad).status_code == 200
        assert size > 0

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=3)
    @frozen_clock()
    def test_rate_limit_121st_save(self, _clock):
        for i in range(3):
            assert self.put(f'r{i}').status_code == 200
        before = SavedDocument.objects.count(), DocumentChange.objects.count()
        response = self.put('r3')
        assert response.status_code == 429
        assert code(response) == 'rate_limited'
        assert (SavedDocument.objects.count(), DocumentChange.objects.count()) == before

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=1)
    @frozen_clock()
    def test_rate_limit_is_per_account(self, _clock):
        assert self.put('a').status_code == 200
        other = Client()
        other.force_login(make_user(2))
        assert save(other, 'b').status_code == 200

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=1)
    def test_rate_limit_resets_next_minute(self):
        with frozen_clock():
            assert self.put('a').status_code == 200
            assert code(self.put('b')) == 'rate_limited'
        with mock.patch.object(save_module.time, 'time', return_value=START_OF_MINUTE + 60):
            assert self.put('b').status_code == 200

    def test_save_that_does_not_grow_allowed_over_storage_limit(self):
        pad = {'text': 'x' * 400}
        assert self.put('a', body=pad).status_code == 200
        assert self.put('b', body=pad).status_code == 200
        # The cap drops below what the account already stores (as a lowered setting would).
        with override_settings(DOCUMENTS_MAX_STORAGE=500):
            response = self.put('a', base_version=1, body={'text': 'x' * 100})
            assert response.status_code == 200, response.content
            response = self.put('a', base_version=2, body={'text': 'y' * 100})
            assert response.status_code == 200, response.content
            # Growing is still refused, and so is a new document.
            assert code(self.put('a', base_version=3, body=pad)) == 'limit_storage'
            assert code(self.put('c')) == 'limit_storage'
