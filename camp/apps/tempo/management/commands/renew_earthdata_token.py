import getpass

import requests

from django.core.management.base import BaseCommand
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

        self.stdout.write(self.style.SUCCESS(
            f'Token renewed. Expires {expires_at:%Y-%m-%d}.'
        ))
