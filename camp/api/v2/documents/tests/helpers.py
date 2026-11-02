import json
from unittest import mock

from django.contrib.auth import get_user_model

from camp.api.v2.accounts.session import session_user_data
from camp.api.v2.documents import save as save_module
from camp.apps.documents.models import measure

User = get_user_model()

BASE = '/api/2.0/documents/'

# Pass as a save() override to leave that key out of the request.
MISSING = object()


def make_user(n):
    return User.objects.create_user(
        f'user{n}@sjvair.com', 'letmein1', full_name=f'User {n}', phone=f'+1559555{n:04d}'
    )


def body(widgets=0):
    return {'widgets': [{'id': f'w{i}', 'type': 'note'} for i in range(widgets)]}


def account_id(client):
    """The account id a save from this signed-in client must carry."""
    user = User.objects.get(pk=client.session['_auth_user_id'])
    return session_user_data(user)['id']


def save(client, id, **overrides):
    """PUT a valid save body for `id` as the client's signed-in user; overrides replace defaults."""
    payload = {
        'kind': 'dashboard',
        'schema_version': 1,
        'name': None,
        'body': body(),
        'deleted_at': None,
        'copied_from': None,
        'base_version': None,
        'changes': [],
        'account_id': account_id(client) if '_auth_user_id' in client.session else None,
        'build_id': 'test-build',
        'snapshot': None,
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not MISSING}
    return client.put(f'{BASE}{id}/', json.dumps(payload), content_type='application/json')


BODY_COLUMNS = ('"documents_saveddocument"."body"', '"documents_documentsnapshot"."body"')


def body_queries(captured):
    """The captured queries that read a document's or snapshot's body column."""
    return [
        query['sql'] for query in captured.captured_queries
        if query['sql'].lstrip().upper().startswith('SELECT')
        and any(column in query['sql'] for column in BODY_COLUMNS)
    ]


# A fixed moment one second into a minute, so a rate-limit test can't straddle two minutes.
START_OF_MINUTE = 1_800_000_000 // 60 * 60 + 1


def frozen_clock():
    return mock.patch.object(save_module.time, 'time', return_value=START_OF_MINUTE)


def padded_body(chars):
    """A body whose measured size is exactly `chars`, padded with a non-ASCII character."""
    empty = measure({'text': ''})
    return {'text': '\u00e9' * (chars - empty)}


def code(response):
    return response.json()['errors']['detail'][0]['code']


def post_snapshot(client, id, **overrides):
    """POST a valid snapshot for `id` as the client's signed-in user; overrides replace defaults."""
    payload = {
        'base_version': 1,
        'schema_version': 1,
        'name': 'Mine',
        'body': body(1),
        'account_id': account_id(client) if '_auth_user_id' in client.session else None,
        'build_id': 'test-build',
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not MISSING}
    return client.post(
        f'{BASE}{id}/snapshots/', json.dumps(payload), content_type='application/json'
    )
