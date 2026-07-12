from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from constance import config as constance_config
from constance.test import override_config

from camp.settings.base import EARTHDATA_TOKEN_NOT_SET


def make_response(status_code=200, json_result=None, ok=True):
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.json.return_value = json_result
    response.raise_for_status = MagicMock()
    return response


class RenewEarthdataTokenTests(TestCase):
    @override_config(EARTHDATA_TOKEN='', EARTHDATA_TOKEN_EXPIRES_AT=EARTHDATA_TOKEN_NOT_SET)
    @patch('builtins.input', return_value='my-username')
    @patch('getpass.getpass', return_value='my-password')
    @patch('camp.apps.tempo.management.commands.renew_earthdata_token.requests.post')
    def test_creates_a_new_token_when_none_is_stored(self, mock_post, mock_getpass, mock_input):
        mock_post.return_value = make_response(json_result={
            'access_token': 'new-token-value',
            'token_type': 'Bearer',
            'expiration_date': '2026-09-09T00:00:00Z',
        })

        call_command('renew_earthdata_token')

        assert constance_config.EARTHDATA_TOKEN == 'new-token-value'
        assert constance_config.EARTHDATA_TOKEN_EXPIRES_AT.year == 2026
        assert constance_config.EARTHDATA_TOKEN_EXPIRES_AT.month == 9
        # No revoke call: nothing was stored to revoke.
        urls_called = [call.args[0] for call in mock_post.call_args_list]
        assert not any('revoke_token' in url for url in urls_called)

    @override_config(EARTHDATA_TOKEN='old-token-value', EARTHDATA_TOKEN_EXPIRES_AT=EARTHDATA_TOKEN_NOT_SET)
    @patch('builtins.input', return_value='my-username')
    @patch('getpass.getpass', return_value='my-password')
    @patch('camp.apps.tempo.management.commands.renew_earthdata_token.requests.post')
    def test_revokes_the_old_token_before_creating_a_new_one(self, mock_post, mock_getpass, mock_input):
        mock_post.side_effect = [
            make_response(status_code=200, ok=True),  # revoke
            make_response(json_result={                # create
                'access_token': 'new-token-value',
                'token_type': 'Bearer',
                'expiration_date': '2026-09-09T00:00:00Z',
            }),
        ]

        call_command('renew_earthdata_token')

        assert mock_post.call_count == 2
        revoke_call, create_call = mock_post.call_args_list
        assert 'revoke_token' in revoke_call.args[0]
        assert revoke_call.kwargs['params'] == {'token': 'old-token-value'}
        assert revoke_call.kwargs['auth'] == ('my-username', 'my-password')
        assert 'revoke_token' not in create_call.args[0]
        assert constance_config.EARTHDATA_TOKEN == 'new-token-value'

    @override_config(EARTHDATA_TOKEN='old-token-value', EARTHDATA_TOKEN_EXPIRES_AT=EARTHDATA_TOKEN_NOT_SET)
    @patch('builtins.input', return_value='my-username')
    @patch('getpass.getpass', return_value='my-password')
    @patch('camp.apps.tempo.management.commands.renew_earthdata_token.requests.post')
    def test_continues_when_revoke_fails(self, mock_post, mock_getpass, mock_input):
        mock_post.side_effect = [
            make_response(status_code=500, ok=False),  # revoke fails
            make_response(json_result={                 # create still proceeds
                'access_token': 'new-token-value',
                'token_type': 'Bearer',
                'expiration_date': '2026-09-09T00:00:00Z',
            }),
        ]

        call_command('renew_earthdata_token')

        assert mock_post.call_count == 2
        assert constance_config.EARTHDATA_TOKEN == 'new-token-value'

    @override_config(EARTHDATA_TOKEN='', EARTHDATA_TOKEN_EXPIRES_AT=EARTHDATA_TOKEN_NOT_SET)
    @patch('builtins.input', return_value='my-username')
    @patch('getpass.getpass', return_value='my-password')
    @patch('camp.apps.tempo.management.commands.renew_earthdata_token.requests.post')
    def test_never_prints_the_password_or_token(self, mock_post, mock_getpass, mock_input):
        mock_post.return_value = make_response(json_result={
            'access_token': 'super-secret-token-value',
            'token_type': 'Bearer',
            'expiration_date': '2026-09-09T00:00:00Z',
        })

        from io import StringIO
        out = StringIO()
        call_command('renew_earthdata_token', stdout=out)

        output = out.getvalue()
        assert 'my-password' not in output
        assert 'super-secret-token-value' not in output
        assert '2026-09-09' in output
