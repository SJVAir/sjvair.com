# TEMPO Earthdata Token Renewal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `EARTHDATA_TOKEN` from a static environment variable to a `django-constance`-managed value that can be renewed without a redeploy, add an interactive management command that renews it without ever persisting NASA Earthdata Login (EDL) credentials, and add a weekly reminder email before the token's 60-day expiry.

**Architecture:** `django-constance` (new dependency, database-backed) stores `EARTHDATA_TOKEN` and `EARTHDATA_TOKEN_EXPIRES_AT`. `TempoClient` prefers the constance value, falling back to `settings.EARTHDATA_TOKEN` for local dev/tests. A management command (`renew_earthdata_token`) prompts for EDL username/password interactively, calls NASA's token API, and writes the result to constance — the credentials never touch disk or a log. A weekly Huey task emails a configured alert list once the stored expiry is within 10 days.

**Tech Stack:** `django-constance==4.3.5` (new), `requests` (already present), `camp.utils.datetime.parse_datetime` (existing).

## Global Constraints

- Tests use plain `assert` statements, not `self.assertFoo()`; use `pytest.raises` for exceptions.
- Timezone is always America/Los_Angeles; use `camp/utils/datetime.py` helpers.
- Never write EDL username/password to disk, logs, or stdout anywhere in this plan's code.
- `EARTHDATA_TOKEN_EXPIRES_AT` is a real `datetime`, not a string — parsed exactly once (in the renewal command), never re-parsed by consumers.

## Design Spec

Full design: `docs/superpowers/specs/2026-07-12-tempo-token-renewal-design.md`. Read it for the NASA EDL Token API contract (confirmed against NASA's own docs) and the reasoning behind rejecting fully-automated renewal.

## Before You Start (operational prerequisite, not code)

**Confirm the exact format of NASA's `expiration_date` response field against a live API call before trusting Task 2's parsing.** Nobody has made this specific call yet in this project (CMR/Harmony endpoints were live-verified earlier; the token endpoint hasn't been). The design spec assumes it's a string `camp.utils.datetime.parse_datetime` can handle (which covers ISO 8601 and Django's configured date-input formats) — if it turns out to need different handling, only `parse_datetime`'s call site in Task 2 needs to change, not the surrounding design. Verifying this requires real EDL credentials, which aren't available in this planning session — either the person implementing this makes one manual `curl -u user:pass -X POST https://urs.earthdata.nasa.gov/api/users/token` call and checks the response shape, or Task 2 ships with the ISO-8601 assumption and gets corrected the first time the command is actually run against production credentials.

---

### Task 1: Add `django-constance`, configure storage, wire `TempoClient`

**Files:**
- Modify: `requirements/base.txt` — add `django-constance==4.3.5`
- Modify: `camp/settings/base.py` — add `'constance'` to `INSTALLED_APPS`, add `CONSTANCE_CONFIG`/`CONSTANCE_BACKEND`/`EARTHDATA_TOKEN_NOT_SET`
- Modify: `camp/apps/tempo/client.py` — `TempoClient.__init__`'s token fallback chain
- Modify: `camp/apps/tempo/tests/test_client.py` — cover the new fallback chain
- Create: migration for constance's own tables (generated, not hand-written)

**Interfaces:**
- Produces: `settings.EARTHDATA_TOKEN_NOT_SET` (a `datetime`, importable from `camp.settings.base` via `django.conf.settings`), `constance.config.EARTHDATA_TOKEN` (str), `constance.config.EARTHDATA_TOKEN_EXPIRES_AT` (datetime).
- Changes: `TempoClient(token=None)`'s fallback order becomes explicit-override → `constance.config.EARTHDATA_TOKEN` → `settings.EARTHDATA_TOKEN`.

- [ ] **Step 1: Add the dependency**

Add to `requirements/base.txt`, alphabetically (after `django-cors-headers`, before `django-debug-toolbar`):

```
django-constance==4.3.5
```

Run `docker compose build web test` to rebuild both images with the new dependency (a plain `pip install` inside a running container won't persist — this project's convention, already established for `netCDF4` earlier in this app).

- [ ] **Step 2: Configure settings**

In `camp/settings/base.py`, add `'constance'` to `INSTALLED_APPS` (alphabetically among the third-party apps, near `django_extensions`/`django_filter` — insert as `'constance',` right before `'corsheaders',`):

```python
    'constance',
    'corsheaders',
```

Near the other tempo-related settings (after `EARTHDATA_TOKEN = env('EARTHDATA_TOKEN', '')`), add:

```python
import datetime as dt

EARTHDATA_TOKEN_NOT_SET = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

CONSTANCE_CONFIG = {
    'EARTHDATA_TOKEN': ('', 'NASA Earthdata Login bearer token for TEMPO ingestion.', str),
    'EARTHDATA_TOKEN_EXPIRES_AT': (
        EARTHDATA_TOKEN_NOT_SET,
        'When the current EARTHDATA_TOKEN expires (set by renew_earthdata_token; informational only).',
        dt.datetime,
    ),
}
CONSTANCE_BACKEND = 'constance.backends.database.DatabaseBackend'
```

`base.py` likely doesn't already import the `datetime` module at the top level under that exact alias — check the top of the file for an existing `import datetime` before adding a second one; if one already exists (e.g. bare `import datetime`), use that name consistently instead of introducing `dt` as a second alias for the same module.

- [ ] **Step 3: Generate and run the migration**

Run: `docker compose run --rm web python manage.py migrate constance`
Expected: applies constance's own bundled migration, creating its config-storage table. No app-specific migration needs to be hand-written or generated — constance ships its own.

- [ ] **Step 4: Write the failing tests**

Add to `camp/apps/tempo/tests/test_client.py` (new test class; leave `FindGranuleTests`/`FetchGranuleBytesTests`/`ResolveCollectionsTests` untouched):

```python
from constance.test import override_config


class TempoClientTokenFallbackTests(TestCase):
    @override_settings(EARTHDATA_TOKEN='settings-token')
    def test_falls_back_to_settings_when_constance_is_unset(self):
        client = TempoClient()
        assert client.token == 'settings-token'

    @override_settings(EARTHDATA_TOKEN='settings-token')
    @override_config(EARTHDATA_TOKEN='constance-token')
    def test_prefers_constance_over_settings(self):
        client = TempoClient()
        assert client.token == 'constance-token'

    @override_settings(EARTHDATA_TOKEN='settings-token')
    @override_config(EARTHDATA_TOKEN='constance-token')
    def test_explicit_token_overrides_everything(self):
        client = TempoClient(token='explicit-token')
        assert client.token == 'explicit-token'
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_client.py::TempoClientTokenFallbackTests -v`
Expected: FAIL — `client.token` still resolves from `settings.EARTHDATA_TOKEN` alone, so `test_prefers_constance_over_settings` fails (`client.token == 'settings-token'`, not `'constance-token'`).

- [ ] **Step 6: Implement**

In `camp/apps/tempo/client.py`, add the import and change `__init__`:

```python
from constance import config as constance_config
```

```python
class TempoClient:
    def __init__(self, token=None):
        self.token = token or constance_config.EARTHDATA_TOKEN or settings.EARTHDATA_TOKEN
        self.session = self._make_session()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_client.py -v`
Expected: 12 passed (9 pre-existing + 3 new).

- [ ] **Step 8: Commit**

```bash
git add requirements/base.txt camp/settings/base.py camp/apps/tempo/client.py camp/apps/tempo/tests/test_client.py
git commit -m "feat(tempo): add django-constance, store EARTHDATA_TOKEN there first"
```

---

### Task 2: `renew_earthdata_token` management command

**Files:**
- Create: `camp/apps/tempo/management/commands/renew_earthdata_token.py`
- Create: `camp/apps/tempo/tests/test_renew_earthdata_token.py`

**Interfaces:**
- Consumes: `constance.config.EARTHDATA_TOKEN` (to know whether an old token needs revoking), `camp.utils.datetime.parse_datetime`.
- Produces: writes `constance.config.EARTHDATA_TOKEN` and `constance.config.EARTHDATA_TOKEN_EXPIRES_AT` as a side effect; no return value consumed by other code.

- [ ] **Step 1: Write the failing tests**

`camp/apps/tempo/tests/test_renew_earthdata_token.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_renew_earthdata_token.py -v`
Expected: FAIL with `django.core.management.base.CommandError: Unknown command: 'renew_earthdata_token'`

- [ ] **Step 3: Implement**

`camp/apps/tempo/management/commands/renew_earthdata_token.py`:

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

        # NASA's expiration_date format is assumed ISO-8601-compatible,
        # per the design spec's "Before You Start" note -- confirm against
        # a real response and adjust only this parsing call if it's wrong.
        expires_at = parse_datetime(data['expiration_date'])

        constance_config.EARTHDATA_TOKEN = data['access_token']
        constance_config.EARTHDATA_TOKEN_EXPIRES_AT = expires_at

        self.stdout.write(self.style.SUCCESS(
            f'Token renewed. Expires {expires_at:%Y-%m-%d}.'
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_renew_earthdata_token.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add camp/apps/tempo/management/commands/renew_earthdata_token.py camp/apps/tempo/tests/test_renew_earthdata_token.py
git commit -m "feat(tempo): add renew_earthdata_token management command"
```

---

### Task 3: Weekly expiry reminder

**Files:**
- Modify: `camp/settings/base.py` — add `TEMPO_ALERT_EMAILS`
- Modify: `camp/apps/tempo/tasks.py` — add `check_earthdata_token_expiry`
- Modify: `camp/apps/tempo/tests/test_tasks.py` — cover the new task

**Interfaces:**
- Consumes: `constance.config.EARTHDATA_TOKEN_EXPIRES_AT`, `settings.EARTHDATA_TOKEN_NOT_SET`, `settings.TEMPO_ALERT_EMAILS`, `camp.utils.datetime.localtime`.

- [ ] **Step 1: Add the setting**

In `camp/settings/base.py`, near `SJVAIR_INACTIVE_ALERT_EMAILS`/`SJVAIR_CONTACT_EMAILS`, add:

```python
TEMPO_ALERT_EMAILS = [email.strip() for email in
    env('TEMPO_ALERT_EMAILS', SERVER_EMAIL).split(',')]
```

- [ ] **Step 2: Write the failing tests**

Add to `camp/apps/tempo/tests/test_tasks.py`:

```python
from datetime import timedelta

from django.core import mail
from django.test import override_settings
from constance.test import override_config

from camp.apps.tempo.tasks import check_earthdata_token_expiry
from camp.settings.base import EARTHDATA_TOKEN_NOT_SET


class CheckEarthdataTokenExpiryTests(TestCase):
    @override_config(EARTHDATA_TOKEN_EXPIRES_AT=EARTHDATA_TOKEN_NOT_SET)
    def test_sends_no_email_when_renewal_has_never_run(self):
        check_earthdata_token_expiry.call_local()

        assert len(mail.outbox) == 0

    def test_sends_no_email_when_expiry_is_far_away(self):
        far_future = localtime() + timedelta(days=45)
        with override_config(EARTHDATA_TOKEN_EXPIRES_AT=far_future):
            check_earthdata_token_expiry.call_local()

        assert len(mail.outbox) == 0

    @override_settings(TEMPO_ALERT_EMAILS=['ops@example.com'])
    def test_sends_an_email_when_within_ten_days_of_expiry(self):
        soon = localtime() + timedelta(days=5)
        with override_config(EARTHDATA_TOKEN_EXPIRES_AT=soon):
            check_earthdata_token_expiry.call_local()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['ops@example.com']
        assert 'renew_earthdata_token' in mail.outbox[0].body

    def test_sends_no_email_when_already_expired_hours_ago_within_the_same_day(self):
        # Comparison is by .date(), not exact timestamp -- expiring
        # earlier today still counts as "0 days left", inside the window.
        just_expired = localtime() - timedelta(hours=2)
        with override_config(EARTHDATA_TOKEN_EXPIRES_AT=just_expired):
            check_earthdata_token_expiry.call_local()

        assert len(mail.outbox) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_tasks.py::CheckEarthdataTokenExpiryTests -v`
Expected: FAIL with `ImportError: cannot import name 'check_earthdata_token_expiry'`

- [ ] **Step 4: Implement**

Add to `camp/apps/tempo/tasks.py`:

```python
from django.conf import settings
from django.core.mail import send_mail
from constance import config as constance_config
```

(add these imports alongside the existing ones at the top of the file)

```python
@db_periodic_task(crontab(day_of_week='1', hour='9', minute='0'), priority=30)
def check_earthdata_token_expiry():
    expires_at = constance_config.EARTHDATA_TOKEN_EXPIRES_AT
    if expires_at == settings.EARTHDATA_TOKEN_NOT_SET:
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_tasks.py -v`
Expected: 11 passed (7 pre-existing + 4 new)

- [ ] **Step 6: Commit**

```bash
git add camp/settings/base.py camp/apps/tempo/tasks.py camp/apps/tempo/tests/test_tasks.py
git commit -m "feat(tempo): add weekly Earthdata token expiry reminder email"
```

---

## Self-Review Notes

**Spec coverage:**
- `django-constance` storage for `EARTHDATA_TOKEN`/`EARTHDATA_TOKEN_EXPIRES_AT`, sentinel default — Task 1. ✅
- `TempoClient` fallback chain (explicit → constance → settings) — Task 1. ✅
- Interactive renewal command, credentials never persisted, revoke-then-create flow, `expiration_date` parsed once — Task 2. ✅
- Weekly reminder email, `TEMPO_ALERT_EMAILS` setting, sentinel-aware skip — Task 3. ✅
- Rejected auto-renewal-via-stored-password approach — a design decision, not something to implement; no task needed.

**Placeholder scan:** no TBD/TODO markers. The "Before You Start" note about `expiration_date`'s unverified format is a flagged external-API uncertainty (consistent with how the original TEMPO ingestion plan handled the same class of uncertainty for CMR/Harmony), not incomplete work on our side — Task 2's code is complete and real, with the assumption clearly commented at its one point of use.

**Type consistency:** `constance.config.EARTHDATA_TOKEN_EXPIRES_AT` is a `datetime` everywhere it's touched — set in Task 2 via `parse_datetime(...)`, read in Task 3 via `.date()` comparison, compared against `settings.EARTHDATA_TOKEN_NOT_SET` (also a `datetime`) in both. `TempoClient.__init__`'s fallback chain (Task 1) and the constance config keys it reads (`EARTHDATA_TOKEN`) match exactly what Task 2's renewal command writes.
