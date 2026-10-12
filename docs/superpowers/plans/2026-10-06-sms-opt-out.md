# SMS Opt-Out (STOP) Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Honor SMS opt-out keywords in English, Spanish, Filipino and Hmong by marking
the phone unverified. Stop sending to numbers Twilio blocks, and tell blocked users
to text START before re-verifying.

**Architecture:**
- A keyword module (`camp/apps/accounts/sms_keywords.py`) classifies inbound text.
- A signature-validated inbound Twilio webhook applies opt-out/opt-in to `User`.
- Both send paths treat Twilio error 21610 as an opt-out.
- A new `User.sms_blocked` flag gates sends and powers a "text START first" error on
  phone-verification requests.

**Tech Stack:** Django, twilio-python (`RequestValidator`, `MessagingResponse`,
`TwilioRestException`), django-phonenumber-field/phonenumbers, django-huey, pytest +
`django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-10-06-sms-opt-out-design.md` (read it first).

## Global Constraints

- **Worktree.** All work is in
  `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/notifications-redesign` on branch
  `feature/alerts-redesign`.
  - First action of every task: `cd` there and confirm with
    `git rev-parse --show-toplevel && git branch --show-current`.
  - Never touch the main checkout `/home/derek/dev/ccac/sjvair.com`.
- **Do not commit or push.** Never `git add -A`.
- **TEST command.** Run from the worktree; the line `fatal: not a git repository` is
  harmless.
  ```
  docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_optout -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/notifications-redesign:/app test pytest <PATHS> -q -p no:cacheprovider --create-db
  ```
  Management commands use the same command with `test python manage.py <cmd>` in place
  of `test pytest ...`.
- **Test style.** `django.test.TestCase`, fixtures (`users.yaml`, `purple-air.yaml`),
  plain `assert`, `pytest.raises` for exceptions. `.call_local()` for huey tasks.
- **Models.** The verbose name is the first positional arg; don't align `=`.
- **Keyword matching.** Exact match on the whole normalized body only.
- **Twilio error code.** Opted out is `21610`.
- **Reply copy is GSM-7/ASCII.** The Spanish copy is written without accents.
- **Fixture user.** `user@sjvair.com` has phone `559-555-5555`, which is E.164
  `+15595555555`, with `phone_verified: true`.

## Review Focus

1. **A message that contains a keyword inside a sentence** ("Please stop by"): must not
   opt out. Test in Task 1.
2. **A sender that isn't a user, or a missing `From`:** 200 with an empty TwiML
   response, no DB writes. Test in Task 3.
3. **A blocked user requesting a password reset by phone:** same response as an
   unblocked user, no send, no account disclosure. Test in Task 4.
4. **A blocked user requests a code:** the rate limit must not be consumed. Test in Task 4.
5. **A 21610 for a phone that matches no user** (the number changed hands): logged, no
   crash. Test in Task 2.

---

### Task 1: `sms_blocked` field, opt-out helpers, keyword module, send guard

**Files:**
- Modify: `camp/apps/accounts/models.py` (field and `User` methods, `send_sms` guard)
- Create: `camp/apps/accounts/migrations/00XX_user_sms_blocked.py` (via makemigrations)
- Create: `camp/apps/accounts/sms_keywords.py`
- Test: `camp/apps/accounts/tests.py` (replace the placeholder content)

**Interfaces (produces):**
- `User.sms_blocked: bool`
- `User.opt_out_of_sms(blocked: bool) -> None`
- `User.clear_sms_block() -> None`
- `sms_keywords.normalize(body: str) -> str`
- `sms_keywords.classify(body: str) -> str | None`, returning one of
  `sms_keywords.TWILIO_OPT_OUT_KIND`, `OPT_OUT_KIND`, `TWILIO_OPT_IN_KIND`
- `sms_keywords.OPTED_OUT_ERROR = 21610`
- `sms_keywords.get_opt_out_reply(language: str) -> str`
- `sms_keywords.get_opt_in_instructions() -> str`

- [ ] **Step 1: Write the failing tests**

Replace the contents of `camp/apps/accounts/tests.py` with:

```python
from unittest.mock import patch

from django.test import TestCase, override_settings

from camp.apps.accounts import sms_keywords
from camp.apps.accounts.models import User


class KeywordTests(TestCase):
    def test_normalize(self):
        assert sms_keywords.normalize('  stop!! ') == 'STOP'
        assert sms_keywords.normalize('Stop   All') == 'STOP ALL'
        assert sms_keywords.normalize('Desuscribír.') == 'DESUSCRIBIR'

    def test_english_keywords_are_twilio_enforced(self):
        for body in ['STOP', 'stop', 'Unsubscribe', 'cancel', 'END', 'quit', 'stop all', 'STOPALL', 'optout', 'revoke']:
            assert sms_keywords.classify(body) == sms_keywords.TWILIO_OPT_OUT_KIND, body

    def test_other_language_keywords(self):
        for body in ['parar', 'Para', 'ALTO', 'detener', 'Cancelar', 'baja', 'desuscribir', 'tigil', 'Hinto', 'itigil', 'tseem', 'nres']:
            assert sms_keywords.classify(body) == sms_keywords.OPT_OUT_KIND, body

    def test_opt_in_keywords(self):
        for body in ['START', 'unstop', 'Yes']:
            assert sms_keywords.classify(body) == sms_keywords.TWILIO_OPT_IN_KIND, body

    def test_keyword_inside_a_sentence_is_not_an_opt_out(self):
        for body in ['Please stop by', 'stop sending at night', 'no pares', 'hello', '']:
            assert sms_keywords.classify(body) is None, body

    def test_opt_out_reply_by_language(self):
        assert sms_keywords.get_opt_out_reply('es').startswith('SJVAir: Ya no recibira')
        assert sms_keywords.get_opt_out_reply('en').startswith("SJVAir: You won't get")
        assert sms_keywords.get_opt_out_reply('hmn') == sms_keywords.get_opt_out_reply('en')
        assert sms_keywords.get_opt_out_reply('tl') == sms_keywords.get_opt_out_reply('en')
        for language in ['en', 'es', 'tl', 'hmn']:
            assert sms_keywords.get_opt_out_reply(language).isascii()

    @override_settings(TWILIO_PHONE_NUMBERS=['+15595550100'])
    def test_opt_in_instructions_name_the_number(self):
        assert sms_keywords.get_opt_in_instructions() == (
            'Text START to (559) 555-0100 to allow texts from SJVAir again, then request a new code.'
        )


class UserSMSStateTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')

    def test_defaults_to_not_blocked(self):
        assert self.user.sms_blocked is False

    def test_opt_out_without_block_only_unverifies(self):
        self.user.opt_out_of_sms(blocked=False)
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    def test_opt_out_with_block(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    def test_clear_sms_block_leaves_phone_unverified(self):
        self.user.opt_out_of_sms(blocked=True)
        self.user.clear_sms_block()
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False
        assert self.user.phone_verified is False

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_send_sms_skips_blocked_user(self, mock_send):
        self.user.opt_out_of_sms(blocked=True)
        assert self.user.send_sms('hello', verify=False) is False
        mock_send.assert_not_called()

    @patch('camp.apps.accounts.tasks.send_sms_message')
    def test_send_sms_still_sends_to_verified_user(self, mock_send):
        self.user.send_sms('hello')
        mock_send.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/accounts/tests.py`
Expected: ImportError (`cannot import name 'sms_keywords'`).

- [ ] **Step 3: Create `camp/apps/accounts/sms_keywords.py`**

```python
import re
import unicodedata

import phonenumbers

from django.conf import settings
from django.utils.translation import gettext as _

# Twilio error code for a send to a number that has opted out.
OPTED_OUT_ERROR = 21610

TWILIO_OPT_OUT_KIND = 'twilio_opt_out'
OPT_OUT_KIND = 'opt_out'
TWILIO_OPT_IN_KIND = 'twilio_opt_in'

# Twilio enforces these itself on a plain number: sends afterwards fail
# with OPTED_OUT_ERROR until the person texts an opt-in keyword.
TWILIO_OPT_OUT = {'STOP', 'STOPALL', 'STOP ALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'OPTOUT', 'REVOKE'}
TWILIO_OPT_IN = {'START', 'UNSTOP', 'YES'}

# Keywords Twilio doesn't know; we enforce them ourselves. The Filipino and
# Hmong words still need a native-speaker check.
OPT_OUT = {
    'es': {'PARAR', 'PARA', 'ALTO', 'DETENER', 'CANCELAR', 'BAJA', 'DESUSCRIBIR'},
    'tl': {'TIGIL', 'HINTO', 'ITIGIL'},
    'hmn': {'TSEEM', 'NRES'},
}

# ASCII only so the reply stays a GSM-7 SMS. Filipino and Hmong fall back
# to English until there are vetted translations.
OPT_OUT_REPLIES = {
    'en': "SJVAir: You won't get any more texts from us. To get alerts again, verify your phone at https://www.sjvair.com/account/",
    'es': 'SJVAir: Ya no recibira mensajes de nosotros. Para volver a recibir alertas, verifique su telefono en https://www.sjvair.com/account/',
}


def normalize(body):
    text = unicodedata.normalize('NFKD', body or '')
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'\s+', ' ', text).strip().upper()
    return text.rstrip('.!?').strip()


def classify(body):
    '''
    Return the opt-out/opt-in kind for an inbound text, or None. Only an
    exact match on the whole message counts, so "please stop by" doesn't.
    '''
    text = normalize(body)
    if text in TWILIO_OPT_OUT:
        return TWILIO_OPT_OUT_KIND
    if text in TWILIO_OPT_IN:
        return TWILIO_OPT_IN_KIND
    if any(text in keywords for keywords in OPT_OUT.values()):
        return OPT_OUT_KIND
    return None


def get_opt_out_reply(language):
    return OPT_OUT_REPLIES.get(language, OPT_OUT_REPLIES['en'])


def get_opt_in_instructions():
    number = phonenumbers.format_number(
        phonenumbers.parse(settings.TWILIO_PHONE_NUMBERS[0], 'US'),
        phonenumbers.PhoneNumberFormat.NATIONAL,
    )
    return _('Text START to {number} to allow texts from SJVAir again, then request a new code.').format(number=number)
```

- [ ] **Step 4: Add the field and methods to `User` in `camp/apps/accounts/models.py`**

After `phone_verified`, add:

```python
    # Twilio is blocking texts to this number (the person texted an English
    # opt-out keyword, or a send failed with error 21610). Cleared when they
    # text START.
    sms_blocked = models.BooleanField(_('SMS blocked by carrier opt-out'), default=False)
```

Replace `send_sms` and add the two helpers after it:

```python
    def send_sms(self, message, verify=True):
        if self.sms_blocked:
            return False
        if self.phone and (self.phone_verified or not verify):
            return tasks.send_sms_message(self.phone, message)
        return False

    def opt_out_of_sms(self, blocked):
        '''
        Stop all texts to this user. Resuming means verifying the phone again.
        '''
        self.phone_verified = False
        self.sms_blocked = self.sms_blocked or blocked
        self.save(update_fields=['phone_verified', 'sms_blocked'])

    def clear_sms_block(self):
        self.sms_blocked = False
        self.save(update_fields=['sms_blocked'])
```

Then generate the migration with the management-command form:
`test python manage.py makemigrations accounts --name user_sms_blocked`.
Confirm it contains only the one `AddField`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/accounts camp/api/v1/accounts camp/api/v2/accounts`
Expected: all pass.

- [ ] **Step 6: Leave uncommitted.** Report the files.

---

### Task 2: Treat Twilio 21610 on send as an opt-out

**Files:**
- Modify: `camp/apps/accounts/tasks.py` (`send_sms_message`)
- Modify: `camp/apps/alerts/tasks.py` (`send_alert_notification`)
- Test: `camp/apps/accounts/tests.py`, `camp/apps/alerts/tests.py`

**Interfaces:**
- **Consumes:** `User.opt_out_of_sms(blocked=True)` and `sms_keywords.OPTED_OUT_ERROR`
  (Task 1).
- **Produces:** `accounts.tasks.handle_opted_out_number(phone_number) -> None`. It is a
  plain function, not a task.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/accounts/tests.py` (add imports `from twilio.base.exceptions import TwilioRestException` and `import pytest`, `from camp.apps.accounts import tasks`):

```python
def opted_out_error():
    return TwilioRestException(
        status=400, uri='https://api.twilio.com/fake',
        msg='Attempt to send to unsubscribed recipient', code=sms_keywords.OPTED_OUT_ERROR,
    )


class SendSMSOptOutTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_opted_out_error_blocks_the_user(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = opted_out_error()

        tasks.send_sms_message.call_local(self.user.phone, 'hello')

        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_opted_out_error_for_unknown_number_is_logged(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = opted_out_error()

        with self.assertLogs('camp.apps.accounts.tasks', level='WARNING'):
            tasks.send_sms_message.call_local('+15595550199', 'hello')

        self.user.refresh_from_db()
        assert self.user.sms_blocked is False

    @patch('camp.apps.accounts.tasks.twilio.rest.Client')
    def test_other_twilio_errors_still_raise(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = TwilioRestException(
            status=400, uri='https://api.twilio.com/fake', msg='Invalid number', code=21211,
        )
        with pytest.raises(TwilioRestException):
            tasks.send_sms_message.call_local(self.user.phone, 'hello')
```

Append to `camp/apps/alerts/tests.py`, inside `NotifySubscribersTests`:

```python
    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_opted_out_error_blocks_the_user(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = TwilioRestException(
            status=400, uri='https://api.twilio.com/fake', msg='Unsubscribed recipient', code=21610,
        )
        self.notify(USG)

        notification = Notification.objects.get()
        assert notification.status == Notification.Status.FAILED
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/accounts/tests.py camp/apps/alerts/tests.py`
Expected: the new tests FAIL (the user is still verified, or the exception propagates).

- [ ] **Step 3: Implement**

Replace `camp/apps/accounts/tasks.py` with:

```python
import logging
from random import choice

from django.conf import settings

import twilio.rest
from twilio.base.exceptions import TwilioRestException

from django_huey import db_task

from camp.apps.accounts import sms_keywords

logger = logging.getLogger(__name__)


def handle_opted_out_number(phone_number):
    '''
    Twilio refused a send because this number opted out: stop texting it.
    '''
    from camp.apps.accounts.models import User

    user = User.objects.filter(phone=phone_number).first()
    if user is None:
        logger.warning('Twilio reports %s opted out, but no user has that number', phone_number)
        return
    user.opt_out_of_sms(blocked=True)


@db_task(priority=100)
def send_sms_message(phone_number, message):
    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )
    try:
        return twilio_client.messages.create(
            to=str(phone_number),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=message,
        )
    except TwilioRestException as exc:
        if exc.code != sms_keywords.OPTED_OUT_ERROR:
            raise
        handle_opted_out_number(phone_number)
```

In `camp/apps/alerts/tasks.py` `send_alert_notification`, inside the existing broad
`except Exception as exc:` branch, add the following before the FAILED save:

```python
        if getattr(exc, 'code', None) == sms_keywords.OPTED_OUT_ERROR:
            handle_opted_out_number(notification.user.phone)
```

Also add the imports:

```python
from camp.apps.accounts import sms_keywords
from camp.apps.accounts.tasks import handle_opted_out_number
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/accounts camp/apps/alerts camp/api/v1/accounts camp/api/v2/accounts`
Expected: all pass.

- [ ] **Step 5: Leave uncommitted.** Report the files.

---

### Task 3: Inbound SMS webhook

**Files:**
- Create: `camp/utils/twilio_signature.py` (shared signature check)
- Modify: `camp/apps/alerts/views.py` (`TwilioStatusCallback` uses the shared check)
- Modify: `camp/apps/accounts/views.py` (add `TwilioInboundSMS`)
- Modify: `camp/urls.py` (route)
- Test: `camp/apps/accounts/tests.py`

**Interfaces:**
- **Consumes:** `sms_keywords.classify`, the `*_KIND` constants and `get_opt_out_reply`;
  `User.opt_out_of_sms` and `User.clear_sms_block` (Task 1).
- **Produces:** `camp.utils.twilio_signature.is_valid_twilio_request(request) -> bool`,
  and the URL name `twilio-inbound-sms`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/accounts/tests.py`. Add the imports:

```python
from django.urls import reverse
from twilio.request_validator import RequestValidator
from camp.apps.alerts.notifications import get_recipients
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.alerts.models import Subscription
```

Then the class:

```python
class InboundSMSTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.user = User.objects.get(email='user@sjvair.com')
        self.url = reverse('twilio-inbound-sms')

    def post(self, body, sender='+15595555555', signed=True):
        data = {'From': sender, 'Body': body}
        signature = 'not-a-real-signature'
        if signed:
            signature = RequestValidator(settings.TWILIO_AUTH_TOKEN).compute_signature(f'http://testserver{self.url}', data)
        return self.client.post(self.url, data, HTTP_X_TWILIO_SIGNATURE=signature)

    def test_invalid_signature_is_rejected(self):
        response = self.post('STOP', signed=False)
        assert response.status_code == 403
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_english_stop_unverifies_and_blocks_without_reply(self):
        response = self.post('stop')
        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/xml')
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is True

    def test_spanish_keyword_unverifies_and_replies_in_spanish(self):
        self.user.language = 'es'
        self.user.save()
        response = self.post('Parar')
        assert response.status_code == 200
        assert b'Ya no recibira' in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False
        assert self.user.sms_blocked is False

    def test_hmong_keyword_replies_in_english(self):
        self.user.language = 'hmn'
        self.user.save()
        response = self.post('nres')
        assert b"You won&apos;t get" in response.content or b"You won't get" in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is False

    def test_start_clears_block_but_keeps_phone_unverified(self):
        self.user.opt_out_of_sms(blocked=True)
        response = self.post('START')
        assert response.status_code == 200
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.sms_blocked is False
        assert self.user.phone_verified is False

    def test_ordinary_text_changes_nothing(self):
        response = self.post('Please stop by the office')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_unknown_sender_returns_empty_response(self):
        response = self.post('STOP', sender='+15595550199')
        assert response.status_code == 200
        assert b'<Message>' not in response.content
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_missing_sender_returns_empty_response(self):
        response = self.post('STOP', sender='')
        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.phone_verified is True

    def test_opted_out_user_is_excluded_from_alert_recipients(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        Subscription.objects.create(user=self.user, monitor=monitor, level='unhealthy_sensitive')
        self.post('STOP')
        assert not get_recipients(monitor).filter(user=self.user).exists()
```

Add `from django.conf import settings` to the imports too.

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/accounts/tests.py`
Expected: NoReverseMatch for `twilio-inbound-sms`.

- [ ] **Step 3: Implement the shared signature check**

Create `camp/utils/twilio_signature.py`:

```python
from django.conf import settings

from twilio.request_validator import RequestValidator


def is_valid_twilio_request(request):
    '''
    True if the request carries a valid X-Twilio-Signature for its URL and
    POST body.
    '''
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    return validator.validate(request.build_absolute_uri(), request.POST, signature)
```

In `camp/apps/alerts/views.py` `TwilioStatusCallback.post`, replace the three
validator lines and the `if not validator.validate(...)` check with:

```python
        if not is_valid_twilio_request(request):
            return HttpResponseForbidden()
```

Import `is_valid_twilio_request`, and drop the now-unused `RequestValidator` and
`settings` imports if nothing else in the file uses them.

- [ ] **Step 4: Add the webhook view**

In `camp/apps/accounts/views.py`, add these imports alongside the existing ones (keep
their grouping style):

```python
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from twilio.twiml.messaging_response import MessagingResponse

from camp.apps.accounts import sms_keywords
from camp.apps.accounts.models import User
from camp.utils.twilio_signature import is_valid_twilio_request
```

(`User` may already be importable; don't duplicate.) Then add the view:

```python
@method_decorator(csrf_exempt, name='dispatch')
class TwilioInboundSMS(View):
    '''
    Twilio forwards every text sent to our number here. Opt-out keywords
    mark the phone unverified; START clears a Twilio-enforced block.
    '''
    def post(self, request, *args, **kwargs):
        if not is_valid_twilio_request(request):
            return HttpResponseForbidden()

        reply = MessagingResponse()
        kind = sms_keywords.classify(request.POST.get('Body', ''))
        sender = request.POST.get('From', '')
        user = User.objects.filter(phone=sender).first() if (kind and sender) else None

        if user is not None:
            if kind == sms_keywords.TWILIO_OPT_OUT_KIND:
                # Twilio sends its own confirmation for these.
                user.opt_out_of_sms(blocked=True)
            elif kind == sms_keywords.OPT_OUT_KIND:
                user.opt_out_of_sms(blocked=False)
                reply.message(sms_keywords.get_opt_out_reply(user.language))
            elif kind == sms_keywords.TWILIO_OPT_IN_KIND:
                user.clear_sms_block()

        return HttpResponse(str(reply), content_type='text/xml')
```

- [ ] **Step 5: Wire the URL**

In `camp/urls.py`, import `TwilioInboundSMS` from `camp.apps.accounts.views`. Add it
next to the status-callback route:

```python
    path('webhooks/twilio/inbound/', TwilioInboundSMS.as_view(), name='twilio-inbound-sms'),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/accounts camp/apps/alerts`
Expected: all pass. That includes the existing `TwilioStatusCallbackTests` after the
signature refactor.

- [ ] **Step 7: Leave uncommitted.** Report the files.

---

### Task 4: "Text START first" on phone-verification requests

**Files:**
- Modify: `camp/apps/accounts/forms.py` (`SendPhoneVerificationForm.clean`)
- Modify: `camp/api/v1/accounts/forms.py` (`SendPhoneVerificationForm.clean`)
- Modify: `camp/api/v2/accounts/forms.py` (`SendPhoneVerificationForm.clean`)
- Test: `camp/api/v2/accounts/tests.py`, `camp/api/v1/accounts/tests.py`

**Interfaces:**
- **Consumes:** `User.sms_blocked`, `sms_keywords.get_opt_in_instructions()` (Task 1),
  and the `send_sms` guard (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `AuthenticationTests` in `camp/api/v2/accounts/tests.py`, and the same pair in
`camp/api/v1/accounts/tests.py` (each file's own module-level `send_phone_verification` /
`password_reset` views and its own `api:v1:...` / `api:v2:...` URL names, matching that
file's existing tests):

```python
    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_blocked_user_is_told_to_text_start(self, send_sms_message):
        self.user.opt_out_of_sms(blocked=True)

        url = reverse("api:v1:account:phone-verify-send")
        request = self.factory.post(url)
        request.user = self.user
        response = send_phone_verification(request)

        assert response.status_code == 400
        assert 'Text START to' in response.content.decode()
        assert not send_sms_message.called
        # The rate limit wasn't consumed, so a retry after texting START works.
        assert not self.user.check_phone_verification_rate_limit()

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_password_reset_for_blocked_user_does_not_reveal_it(self, send_sms_message):
        self.user.opt_out_of_sms(blocked=True)

        url = reverse("api:v1:account:password-reset")
        request = self.factory.post(url, {"phone": "559-555-5555"}, content_type="application/json")
        response = password_reset(request)

        assert response.status_code == 200
        assert 'Text START' not in response.content.decode()
        assert not send_sms_message.called
```

Use the URL name prefix that file's existing phone tests use (the v2 test file
currently reverses `api:v1:...` names; mirror whatever its existing tests do).

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/api/v1/accounts camp/api/v2/accounts`
Expected: `test_blocked_user_is_told_to_text_start` FAILS, with status 204, in both
versions. The password-reset test may already pass thanks to Task 1's `send_sms` guard;
that's fine and expected.

- [ ] **Step 3: Implement**

In each of the three `SendPhoneVerificationForm` classes, change `clean` to check the
block before the rate limit. Add the `sms_keywords` import to each file:
`from camp.apps.accounts import sms_keywords`.

```python
    def clean(self):
        if self.user.sms_blocked:
            raise forms.ValidationError(sms_keywords.get_opt_in_instructions(), code='sms_blocked')
        self.check_rate_limit()
        return self.cleaned_data
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/accounts camp/api/v1/accounts camp/api/v2/accounts camp/apps/alerts`
Expected: all pass.

Then run the full suite once: TEST with `<PATHS>` = `camp -n 4 --dist loadscope`.
Expected: all pass.

- [ ] **Step 5: Leave uncommitted.** Report the files and `git status --short`.
