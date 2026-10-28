import json
from unittest import mock

from django.conf import settings
from django.test import Client, TestCase, override_settings

from camp.api.v2.documents import save as save_module
from camp.apps.documents.models import (
    BlockedBuild, DocumentChange, PurgedDocument, SavedDocument, measure,
)

from .helpers import BASE, MISSING, account_id, body, make_user, save


def code(response):
    return response.json()['errors']['detail'][0]['code']


def change(n):
    return {'schema_version': 1, 'change': {'op': 'set', 'n': n}}


def padded_body(chars):
    """A body whose measured size is exactly `chars`, padded with a non-ASCII character."""
    empty = measure({'text': ''})
    return {'text': 'é' * (chars - empty)}


class SaveTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)
        self.bob_client = Client()
        self.bob_client.force_login(self.bob)

    def create(self, id='doc', **overrides):
        response = save(self.client, id, **overrides)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']

    def test_signed_out_401(self):
        response = save(Client(), 'doc')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertFalse(SavedDocument.objects.exists())

    def test_create_then_save_increments_version(self):
        created = self.create(body=body(1), name='First', changes=[change(1)])
        self.assertEqual(created['version'], 1)
        self.assertIn('updated_at', created)
        doc = SavedDocument.objects.get(pk='doc')
        self.assertEqual(doc.owner, self.alice)
        self.assertEqual(doc.version, 1)
        self.assertEqual(doc.name, 'First')
        self.assertEqual(doc.body, body(1))
        self.assertEqual(doc.size, measure(body(1)))

        response = save(self.client, 'doc', base_version=1, body=body(2), changes=[change(2)])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response.json()['data']['version'], 2)
        doc.refresh_from_db()
        self.assertEqual(doc.version, 2)
        self.assertEqual(doc.body, body(2))
        self.assertEqual(doc.size, measure(body(2)))
        log = list(doc.changes.order_by('version').values_list('version', 'entries'))
        self.assertEqual(log, [(1, [change(1)]), (2, [change(2)])])

    def test_same_base_twice_second_is_stale(self):
        self.create()
        first = save(self.client, 'doc', base_version=1, body=body(1),
                     changes=[change(1), change(2)])
        self.assertEqual(first.status_code, 200)
        second = save(self.client, 'doc', base_version=1, body=body(3), changes=[change(3)])
        self.assertEqual(second.status_code, 409)
        self.assertEqual(code(second), 'stale_base')
        data = second.json()['data']
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['changes'], [
            {'version': 2, 'schema_version': 1, 'change': change(1)['change']},
            {'version': 2, 'schema_version': 1, 'change': change(2)['change']},
        ])
        self.assertEqual(data['document']['body'], body(1))
        self.assertEqual(data['document']['version'], 2)
        self.assertEqual(data['document']['id'], 'doc')
        self.assertEqual(SavedDocument.objects.get(pk='doc').body, body(1))

    def test_create_over_existing_own_is_stale_with_null_changes(self):
        self.create(body=body(1))
        response = save(self.client, 'doc', base_version=None, body=body(2))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(code(response), 'stale_base')
        data = response.json()['data']
        self.assertIsNone(data['changes'])
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['document']['body'], body(1))

    def test_client_ahead_of_server_is_stale_with_null_changes(self):
        self.create()
        response = save(self.client, 'doc', base_version=5)
        self.assertEqual(code(response), 'stale_base')
        self.assertIsNone(response.json()['data']['changes'])

    def test_other_owner_id_taken(self):
        self.assertEqual(save(self.bob_client, 'doc').status_code, 200)
        for base in [None, 1]:
            response = save(self.client, 'doc', base_version=base)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(code(response), 'id_taken')
            self.assertNotIn('data', response.json())
        self.assertEqual(SavedDocument.objects.get(pk='doc').owner, self.bob)

    def test_purged_own_is_gone(self):
        PurgedDocument.objects.create(id='bye', owner=self.alice)
        response = save(self.client, 'bye')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(code(response), 'gone')

    def test_purged_other_is_id_taken(self):
        PurgedDocument.objects.create(id='bye', owner=self.bob)
        response = save(self.client, 'bye')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(code(response), 'id_taken')

    def test_missing_with_base_is_not_found(self):
        response = save(self.client, 'doc', base_version=3)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(code(response), 'not_found')

    def test_schema_downgrade_refused(self):
        self.create(schema_version=2)
        response = save(self.client, 'doc', base_version=1, schema_version=1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(code(response), 'schema_downgrade')
        self.assertEqual(response.json()['data'], {'schema_version': 2})
        # The same or a newer schema is fine.
        self.assertEqual(save(self.client, 'doc', base_version=1, schema_version=3).status_code, 200)
        self.assertEqual(SavedDocument.objects.get(pk='doc').schema_version, 3)

    def test_account_mismatch_has_signed_in_as(self):
        response = save(self.client, 'doc', account_id=account_id(self.bob_client))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(code(response), 'account_mismatch')
        self.assertEqual(response.json()['data'], {'signed_in_as': account_id(self.client)})
        self.assertFalse(SavedDocument.objects.exists())

    def test_blocked_build(self):
        BlockedBuild.objects.create(build_id='bad-build')
        response = save(self.client, 'doc', build_id='bad-build')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(code(response), 'build_blocked')
        self.assertEqual(save(self.client, 'doc', build_id='good-build').status_code, 200)

    def test_invalid_fields_listed(self):
        response = save(
            self.client, 'doc',
            schema_version=0, name='x' * 101, body=[], deleted_at='not a date',
            copied_from=5, base_version=-1, changes=[{'schema_version': 1}],
            account_id=7, build_id='b' * 65, snapshot='daily',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(code(response), 'invalid')
        fields = response.json()['data']['fields']
        self.assertEqual(
            set(fields),
            {'schema_version', 'name', 'body', 'deleted_at', 'copied_from', 'base_version',
             'changes', 'account_id', 'build_id', 'snapshot'},
        )
        for messages in fields.values():
            self.assertTrue(messages and all(isinstance(m, str) for m in messages))

    def test_invalid_types_and_missing_fields(self):
        response = save(
            self.client, 'doc', schema_version=True, base_version='3', changes={},
            name=MISSING, build_id=MISSING,
        )
        fields = response.json()['data']['fields']
        self.assertEqual(set(fields), {'schema_version', 'base_version', 'changes', 'name',
                                       'build_id'})
        response = save(self.client, 'doc', changes=[{'schema_version': 0, 'change': []}])
        self.assertEqual(set(response.json()['data']['fields']), {'changes'})

    def test_request_not_an_object_is_invalid(self):
        response = self.client.put(f'{BASE}doc/', '[1, 2]', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(code(response), 'invalid')
        self.assertEqual(set(response.json()['data']['fields']), {'request'})
        # A well-formed but impossible date is a field error, not a crash.
        response = save(self.client, 'doc', deleted_at='2026-13-45T00:00:00Z')
        self.assertEqual(set(response.json()['data']['fields']), {'deleted_at'})

    def test_nan_in_body_is_invalid(self):
        response = self.client.put(
            f'{BASE}doc/',
            json.dumps({
                'kind': 'dashboard', 'schema_version': 1, 'name': None, 'body': {'x': 'NAN'},
                'deleted_at': None, 'copied_from': None, 'base_version': None, 'changes': [],
                'account_id': account_id(self.client), 'build_id': 'b', 'snapshot': None,
            }).replace('"NAN"', 'NaN'),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()['data']['fields']), {'body'})

    def test_bad_ids_invalid(self):
        for bad in ['export', 'shared', 'has.dot', 'x' * 65]:
            response = save(self.client, bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertEqual(code(response), 'invalid')
            self.assertIn('id', response.json()['data']['fields'])
        self.assertFalse(SavedDocument.objects.exists())

    def test_reserved_ids_invalid(self):
        # profile/, export/, and shared/ are fixed routes ahead of <id>/, so a PUT there never
        # reaches the save, and a document with one of those ids would have its sub-routes
        # shadowed (shared/changes/ is a share link); validation refuses the ids.
        for reserved in ['profile', 'export', 'shared']:
            _, errors = save_module.validate({}, reserved)
            self.assertIn('id', errors, reserved)

    def test_kind_other_than_dashboard_invalid(self):
        response = save(self.client, 'doc', kind='notebook')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(code(response), 'invalid')
        self.assertIn('kind', response.json()['data']['fields'])

    def test_deleted_at_and_copied_from_stored(self):
        self.create(deleted_at='2026-10-28T12:00:00Z', copied_from='original')
        doc = SavedDocument.objects.get(pk='doc')
        self.assertEqual(doc.deleted_at.isoformat(), '2026-10-28T12:00:00+00:00')
        self.assertEqual(doc.copied_from, 'original')
        # Restoring clears deleted_at.
        save(self.client, 'doc', base_version=1, deleted_at=None, copied_from='original')
        doc.refresh_from_db()
        self.assertIsNone(doc.deleted_at)

    def test_body_exactly_limit_with_non_ascii_accepted(self):
        big = padded_body(settings.DOCUMENTS_MAX_BODY)
        self.assertEqual(measure(big), 1_000_000)
        self.create(body=big)
        self.assertEqual(SavedDocument.objects.get(pk='doc').size, 1_000_000)

    def test_body_exactly_limit_with_non_ascii_plus_one_refused(self):
        response = save(self.client, 'doc', body=padded_body(settings.DOCUMENTS_MAX_BODY + 1))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')
        self.assertFalse(SavedDocument.objects.exists())

    @override_settings(DOCUMENTS_MAX_CHANGES=100)
    def test_changes_over_limit_refused(self):
        changes = [{'schema_version': 1, 'change': {'t': 'x'}}]
        empty = measure(changes) - 1
        changes[0]['change']['t'] = 'é' * (100 - empty)
        self.assertEqual(measure(changes), 100)
        self.assertEqual(save(self.client, 'doc', changes=changes).status_code, 200)
        changes[0]['change']['t'] += 'é'
        response = save(self.client, 'doc', base_version=1, changes=changes)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')

    @override_settings(DOCUMENTS_LOG_LIMIT=3)
    def test_log_trimmed_to_limit(self):
        self.create(changes=[change(1)])
        for version in range(1, 5):
            response = save(self.client, 'doc', base_version=version,
                            changes=[change(version + 1)])
            self.assertEqual(response.status_code, 200)
        versions = list(DocumentChange.objects.filter(document_id='doc')
                        .order_by('version').values_list('version', flat=True))
        self.assertEqual(versions, [3, 4, 5])
        # A base inside the kept log still gets its changes; one before it gets null.
        kept = save(self.client, 'doc', base_version=2).json()['data']['changes']
        self.assertEqual([e['version'] for e in kept], [3, 4, 5])
        self.assertIsNone(save(self.client, 'doc', base_version=1).json()['data']['changes'])

    def test_log_gap_gives_null_changes(self):
        self.create(changes=[change(1)])
        save(self.client, 'doc', base_version=1, changes=[change(2)])
        save(self.client, 'doc', base_version=2, changes=[change(3)])
        DocumentChange.objects.filter(document_id='doc', version=2).delete()
        response = save(self.client, 'doc', base_version=1)
        self.assertEqual(code(response), 'stale_base')
        self.assertIsNone(response.json()['data']['changes'])
        # A range that skips the gap is still served.
        response = save(self.client, 'doc', base_version=2)
        self.assertEqual(len(response.json()['data']['changes']), 1)

    def test_empty_changes_still_logged(self):
        self.create(changes=[])
        save(self.client, 'doc', base_version=1, changes=[change(2)])
        response = save(self.client, 'doc', base_version=1)
        self.assertEqual(response.json()['data']['changes'],
                         [{'version': 2, 'schema_version': 1, 'change': change(2)['change']}])

    def test_refusals_write_nothing(self):
        self.create(body=body(1), changes=[change(1)])
        save(self.bob_client, 'bobs')
        PurgedDocument.objects.create(id='bye', owner=self.alice)
        PurgedDocument.objects.create(id='bobbye', owner=self.bob)
        BlockedBuild.objects.create(build_id='bad-build')

        def state():
            return (
                list(SavedDocument.objects.order_by('pk').values()),
                list(DocumentChange.objects.order_by('pk').values()),
                list(PurgedDocument.objects.order_by('pk').values()),
            )

        before = state()
        refusals = [
            ('invalid', save(self.client, 'doc', base_version=1, kind='notebook')),
            ('invalid', save(self.client, 'profile')),
            ('too_large', save(self.client, 'doc', base_version=1,
                               body=padded_body(settings.DOCUMENTS_MAX_BODY + 1))),
            ('build_blocked', save(self.client, 'doc', base_version=1, build_id='bad-build')),
            ('account_mismatch', save(self.client, 'doc', base_version=1, account_id='nope')),
            ('gone', save(self.client, 'bye')),
            ('id_taken', save(self.client, 'bobbye')),
            ('id_taken', save(self.client, 'bobs', base_version=1)),
            ('not_found', save(self.client, 'new', base_version=1)),
            ('stale_base', save(self.client, 'doc', base_version=None, body=body(9))),
            ('stale_base', save(self.client, 'doc', base_version=0, body=body(9))),
        ]
        for expected, response in refusals:
            self.assertEqual(code(response), expected)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(state(), before, expected)

        # A schema downgrade needs a newer stored schema first.
        save(self.client, 'doc', base_version=1, schema_version=2)
        before = state()
        response = save(self.client, 'doc', base_version=2, schema_version=1, body=body(9))
        self.assertEqual(code(response), 'schema_downgrade')
        self.assertEqual(state(), before)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000)
    def test_session_save_uses_documents_cap_not_site_cap(self):
        # Over the site cap but under DOCUMENTS_MAX_REQUEST_BYTES: a signed-in save goes through.
        self.create(body=padded_body(2000))

    @override_settings(DOCUMENTS_MAX_REQUEST_BYTES=1000)
    def test_session_save_over_documents_cap_is_too_large(self):
        response = save(self.client, 'doc', body=padded_body(2000))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertFalse(SavedDocument.objects.exists())

    @override_settings(DOCUMENTS_MAX_REQUEST_BYTES=1000)
    def test_invalid_content_length_is_too_large(self):
        response = self.client.put(f'{BASE}doc/', '{}', content_type='application/json',
                                   CONTENT_LENGTH='lots')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000)
    def test_signed_out_save_keeps_site_cap(self):
        # Over the site cap: refused before resticus authenticates, never buffered past it.
        response = save(Client(), 'doc', body=padded_body(2000))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')
        self.assertEqual(response['Cache-Control'], 'no-store')
        # Under it: the usual 401.
        self.assertEqual(save(Client(), 'doc').status_code, 401)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000)
    def test_other_endpoints_keep_site_cap(self):
        payload = json.dumps({'text': 'x' * 2000})
        # Another API endpoint answers Django's own 400 for a request over the cap.
        response = self.client.put('/api/2.0/time/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        # So does every documents method other than a save (here: the list).
        response = self.client.put(BASE, payload, content_type='application/json')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(code(response), 'too_large')

    def test_create_race_reruns_checks(self):
        # Another request inserted this id after our locked lookup missed it.
        self.create(body=body(1))
        real = save_module.locked_row
        calls = []

        def miss_first(id):
            calls.append(id)
            return None if len(calls) == 1 else real(id)

        with mock.patch.object(save_module, 'locked_row', side_effect=miss_first):
            response = save(self.client, 'doc', body=body(2))
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(code(response), 'stale_base')
        self.assertIsNone(response.json()['data']['changes'])
        doc = SavedDocument.objects.get(pk='doc')
        self.assertEqual((doc.version, doc.body), (1, body(1)))
        self.assertEqual(DocumentChange.objects.filter(document=doc).count(), 1)
