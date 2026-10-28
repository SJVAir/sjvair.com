import json

from django.contrib.auth import get_user_model

from camp.api.v2.accounts.session import session_user_data

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
