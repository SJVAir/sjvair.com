# TEMPO Earthdata Token Renewal Design

**Date:** 2026-07-12
**Status:** Draft

## Overview

NASA Earthdata Login (EDL) bearer tokens expire after 60 days. `EARTHDATA_TOKEN` is currently a plain environment variable (`camp/settings/base.py`), which means renewing it today means generating a new token by hand in the EDL web UI and redeploying with an updated Heroku config var — an easy step to forget, with no warning before the token actually expires and TEMPO ingestion silently starts failing.

This spec covers three pieces: storing the token somewhere it can be updated without a redeploy, a management command that renews it without ever persisting your EDL username/password anywhere, and a recurring reminder before it expires.

**Explicitly rejected approach:** automatically renewing the token on a schedule using a stored EDL username/password. A leaked bearer token is scoped and self-expiring; a leaked EDL password is a full account compromise. Trading a 60-day scoped credential for a persistently-stored, more powerful one is a worse security posture than the manual step it replaces. The design below keeps the human in the loop for the one part that actually needs a secret (running the renewal command), and automates only the parts that don't (storage, reminders).

## NASA EDL Token API

Confirmed against NASA's own documentation (`https://urs.earthdata.nasa.gov/documentation/for_users/user_token`), 2026-07-12. Base URL `https://urs.earthdata.nasa.gov`; all operations authenticate via HTTP Basic Auth (EDL username/password), used transiently, not stored:

| Operation | Method + Path | Response |
|---|---|---|
| Create token | `POST /api/users/token` | `{access_token, token_type, expiration_date}` |
| List tokens | `GET /api/users/tokens` | array of `{access_token, expiration_date}` |
| Revoke token | `POST /api/users/revoke_token?token=...` | 200, no body |
| Find-or-create | `POST /api/users/find_or_create_token` | same shape as create |

**Constraint:** a user may have at most 2 valid tokens at once. **Find-or-create is deliberately not used for renewal** — it would likely just hand back the existing, still-valid-but-soon-to-expire token instead of minting a fresh 60-day one. The renewal flow explicitly revokes the currently-stored token (if any), then creates a new one.

**Unverified, flag for Task 1:** the exact format of `expiration_date` (a date string vs. a full timestamp — the EDL web UI shows both a date and a time, e.g. "09-9-2026 9:46pm EDT") hasn't been confirmed against a live API response. Task 1 below includes a manual verification step before the parsing logic is trusted. Also unverified: whether `constance`'s `datetime.datetime` field type accepts `None` as its declared default (some Django-style field type declarations require a real value of the matching type) — Task 1 should confirm this against the actual installed `constance` version and fall back to a sentinel past `datetime` if `None` isn't accepted.

## Storage: `django-constance`

New dependency (`requirements/base.txt`) — the first use of `constance` in this codebase, chosen because the token needs to be admin-editable at runtime without a redeploy, and future runtime-editable settings (not just this one) can reuse the same mechanism.

```python
# camp/settings/base.py
import datetime as dt

CONSTANCE_CONFIG = {
    'EARTHDATA_TOKEN': ('', 'NASA Earthdata Login bearer token for TEMPO ingestion.', str),
    'EARTHDATA_TOKEN_EXPIRES_AT': (None, 'When the current EARTHDATA_TOKEN expires (set by renew_earthdata_token; informational only).', dt.datetime),
}
CONSTANCE_BACKEND = 'constance.backends.database.DatabaseBackend'
```

`EARTHDATA_TOKEN_EXPIRES_AT` is stored as a real `datetime`, not a string — NASA's raw `expiration_date` value is parsed exactly once, in the renewal command below (the only place that raw API response is ever seen), via `camp.utils.datetime.parse_datetime` (the existing codebase utility that already handles flexible date-string parsing and returns a timezone-aware value). Every consumer after that — the reminder task, any future admin display — works with a normal Python `datetime`, not a string it has to re-parse. The exact format NASA sends (see "Unverified" note above) only matters to that one parsing call.

`constance` ships its own migrations and admin integration (`Sites > Constance > Config` in the Django admin) — no custom model needed.

## `TempoClient` changes

`camp/apps/tempo/client.py`'s `__init__` currently does `self.token = token or settings.EARTHDATA_TOKEN`. Change the fallback chain to prefer the dynamic, renewable value first:

```python
from constance import config as constance_config

class TempoClient:
    def __init__(self, token=None):
        self.token = token or constance_config.EARTHDATA_TOKEN or settings.EARTHDATA_TOKEN
```

`constance_config.EARTHDATA_TOKEN` defaults to `''` (falsy) until the renewal command runs at least once, so this falls through to `settings.EARTHDATA_TOKEN` cleanly — existing tests (`@override_settings(EARTHDATA_TOKEN='test-token')`) keep working unchanged, since a fresh test database never has a constance row overriding it. `settings.EARTHDATA_TOKEN` stays as the initial-bootstrap/local-dev path; production moves to the constance-managed value once the renewal command has been run there at least once.

## Renewal command

`camp/apps/tempo/management/commands/renew_earthdata_token.py` — interactive only, never accepts credentials as CLI arguments (would leak into shell history and process listings):

```python
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

        # NASA's expiration_date format is confirmed in Task 1 against a
        # real response before this parsing is trusted -- parse_datetime
        # (camp/utils/datetime.py) already handles the common date-string
        # formats and returns a timezone-aware value.
        expires_at = parse_datetime(data['expiration_date'])

        constance_config.EARTHDATA_TOKEN = data['access_token']
        constance_config.EARTHDATA_TOKEN_EXPIRES_AT = expires_at

        self.stdout.write(self.style.SUCCESS(
            f'Token renewed. Expires {expires_at:%Y-%m-%d}.'
        ))
```

Run via `heroku run python manage.py renew_earthdata_token` in production (a one-off dyno with an attached TTY — `getpass` requires one). Never prints the token itself, only the expiry date, so it's safe to appear in Heroku's run-output logs.

## Expiry reminder

New setting, mirroring the existing `SJVAIR_INACTIVE_ALERT_EMAILS` pattern (`camp/settings/base.py`) rather than inventing a new convention:

```python
TEMPO_ALERT_EMAILS = [email.strip() for email in
    env('TEMPO_ALERT_EMAILS', SERVER_EMAIL).split(',')]
```

`camp/apps/tempo/tasks.py` gains a weekly check:

```python
@db_periodic_task(crontab(day_of_week='1', hour='9', minute='0'), priority=30)
def check_earthdata_token_expiry():
    expires_at = constance_config.EARTHDATA_TOKEN_EXPIRES_AT
    if not expires_at:
        return  # renewal command has never been run; nothing to warn about yet

    days_left = (expires_at.date() - localtime().date()).days
    if days_left <= 10:
        send_mail(
            subject=f'TEMPO Earthdata token expires in {days_left} day{"s" if days_left != 1 else ""}',
            message=(
                'Run `heroku run python manage.py renew_earthdata_token` to renew it. '
                'TEMPO ingestion will silently stop working once it expires.'
            ),
            from_email=settings.SERVER_EMAIL,
            recipient_list=settings.TEMPO_ALERT_EMAILS,
        )
```

Since `EARTHDATA_TOKEN_EXPIRES_AT` is already a real `datetime` (parsed once, in the renewal command above), this task does plain date arithmetic — no parsing of its own. Runs weekly rather than once, so it keeps nagging every week the token is within the 10-day window until someone actually renews it — a single easy-to-miss email is worse than a recurring one that naturally stops once `EARTHDATA_TOKEN_EXPIRES_AT` moves back out past the threshold.

## Deferred

- Automatic credential-free renewal (e.g. OAuth device flow, if EDL ever supports one) -- not available today per EDL's documented auth model, which is Basic Auth only for the token API.
- Multi-user credential support -- this assumes one shared EDL account (already the case for `EARTHDATA_TOKEN` today), not per-developer tokens.
