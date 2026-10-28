import json

from django.contrib.auth import get_user_model

User = get_user_model()

BASE = '/api/2.0/documents/'


def make_user(n):
    return User.objects.create_user(
        f'user{n}@sjvair.com', 'letmein1', full_name=f'User {n}', phone=f'+1559555{n:04d}'
    )


def body(widgets=0):
    return {'widgets': [{'id': f'w{i}', 'type': 'note'} for i in range(widgets)]}


def save(client, id, **overrides):
    """PUT a valid save body for `id`; keyword overrides replace the defaults."""
    payload = {
        'kind': 'dashboard',
        'schema_version': 1,
        'name': None,
        'body': body(),
        'deleted_at': None,
        'copied_from': None,
        'base_version': None,
        'changes': [],
        'account_id': None,
        'build_id': None,
        'snapshot': None,
    }
    payload.update(overrides)
    return client.put(f'{BASE}{id}/', json.dumps(payload), content_type='application/json')
