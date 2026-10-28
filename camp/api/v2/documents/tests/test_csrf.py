import json

import pytest

from django.middleware.csrf import get_token
from django.test import Client, TestCase

from .helpers import BASE, account_id, body, make_user


class SessionCsrfTests(TestCase):
    def setUp(self):
        try:
            from resticus.auth import enforce_csrf  # noqa: F401
        except ImportError:
            pytest.skip('resticus without the session CSRF fix')
        self.user = make_user(1)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def put(self, **headers):
        payload = {
            'kind': 'dashboard', 'schema_version': 1, 'name': None, 'body': body(),
            'deleted_at': None, 'copied_from': None, 'base_version': None, 'changes': [],
            'account_id': account_id(self.client), 'build_id': 'test-build', 'snapshot': None,
        }
        return self.client.put(
            f'{BASE}doc/', json.dumps(payload), content_type='application/json', **headers
        )

    def test_session_save_without_csrf_refused(self):
        assert self.put().status_code == 403

    def test_session_save_with_csrf_accepted(self):
        # A GET sets the csrftoken cookie; its value is the header token.
        self.client.get(f'{BASE}')
        token = self.client.cookies.get('csrftoken')
        if token is None:
            from django.http import HttpRequest
            request = HttpRequest()
            request.COOKIES = {}
            token = get_token(request)
        else:
            token = token.value
        self.client.cookies['csrftoken'] = token
        assert self.put(HTTP_X_CSRFTOKEN=token).status_code == 200
