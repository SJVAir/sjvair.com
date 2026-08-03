import getpass

import requests

from django.core.management.base import BaseCommand, CommandError
from constance import config as constance_config

from camp.utils.datetime import parse_datetime

EDL_BASE_URL = 'https://urs.earthdata.nasa.gov'


class Command(BaseCommand):
    help = (
        'Prompts for your NASA Earthdata Login username and password, revokes '
        'the currently-stored token (if any) to stay under EDL\'s 2-token cap, '
        'mints a fresh one, and saves it via constance. Credentials are used '
        'only for this one request and are never written to disk or logged.'
    )

    def handle(self, *args, **options):
        username = input('Earthdata username: ')
        password = getpass.getpass('Earthdata password: ')
        auth = (username, password)

        # Everything below is wrapped so that a failure (e.g. a mistyped
        # password, or a DB write failing partway through saving the new
        # token) raises CommandError rather than propagating -- Django's
        # run_from_argv catches CommandError before it reaches sys.excepthook,
        # keeping the plaintext password out of Sentry's default
        # local-variable exception capture. The constance writes below are
        # deliberately inside this block too: password/auth are still live
        # locals in this frame until handle() returns, so any exception
        # raised anywhere in here -- not just the HTTP calls -- must be
        # caught here.
        try:
            old_token = constance_config.EARTHDATA_TOKEN
            if old_token:
                revoke_response = requests.post(
                    f'{EDL_BASE_URL}/api/users/revoke_token',
                    params={'token': old_token},
                    auth=auth,
                )
                if not revoke_response.ok:
                    self.stdout.write(self.style.WARNING(
                        f'Could not revoke the previous token (status {revoke_response.status_code}) -- continuing anyway.'
                    ))

            response = requests.post(f'{EDL_BASE_URL}/api/users/token', auth=auth)
            response.raise_for_status()
            data = response.json()

            # NASA's expiration_date format is assumed ISO-8601-compatible,
            # per the design spec's "Before You Start" note -- confirm against
            # a real response and adjust only this parsing call if it's wrong.
            expires_at = parse_datetime(data['expiration_date'])

            constance_config.EARTHDATA_TOKEN = data['access_token']
            constance_config.EARTHDATA_TOKEN_EXPIRES_AT = expires_at
        except Exception as exc:
            raise CommandError('Token renewal failed -- check your username and password and try again.') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Token renewed. Expires {expires_at:%Y-%m-%d}.'
        ))
