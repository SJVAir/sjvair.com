# SMS Opt-Out (STOP) Handling — Design Spec

**Date:** 2026-10-06
**Status:** Draft, pending Derek's review
**Builds on:** `2026-10-06-alert-notification-throttling-design.md` (PR #246)

## Why

US SMS rules require honoring opt-out keywords. SJVAir users choose English, Filipino,
Hmong or Spanish (`User.language`), but today nothing processes inbound texts:

- **English is partly covered.** Twilio itself blocks a number that texts an English
  opt-out keyword: every later send to it fails with error 21610.
- **Our side doesn't know.** We keep queuing (and logging) failed alert texts, and the
  user is never marked as opted out.
- **Other languages do nothing.** Twilio doesn't recognize them, so we keep texting
  someone who said PARAR.

## Goals

- **Any opt-out keyword stops texts.** A keyword in any supported language stops all
  SMS to that user: alerts, reminders and anything else gated on a verified phone.
- **Re-verify to resume.** Resuming means going through phone verification again;
  there's no keyword-based resume.
- **Stop paying for blocked texts.** No Twilio sends to numbers we know are blocked.
- **No dead end.** A user who opted out with an English keyword and later re-verifies
  on the site is told to text START first. Otherwise Twilio would silently block the
  verification code.

## Non-Goals

- A Twilio Messaging Service or Advanced Opt-Out. Production has one number, and the
  keyword handling lives in our code.
- HELP / INFO keyword replies. Twilio's default handles English HELP.
- Deleting subscriptions. They persist, and texting resumes after re-verification.

---

## 1. Data model (`camp/apps/accounts/models.py`)

`User` gains:

- `sms_blocked = models.BooleanField(_('SMS blocked by carrier opt-out'), default=False)`.
  Set to true when Twilio is blocking messages to this number: an English keyword was
  received, or a send failed with 21610. Set to false when Twilio forwards a
  START/UNSTOP/YES from the number.

An opt-out never deletes anything. It sets `phone_verified = False` and, when Twilio
enforces the block, sets `sms_blocked`.

## 2. Keywords (`camp/apps/accounts/sms_keywords.py`)

One module of constants, easy to edit:

```python
# Twilio enforces these itself on a plain number (sends then fail with 21610).
TWILIO_OPT_OUT = {'STOP', 'STOPALL', 'STOP ALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'OPTOUT', 'REVOKE'}
TWILIO_OPT_IN = {'START', 'UNSTOP', 'YES'}

# We enforce these ourselves. Filipino and Hmong need a native-speaker check.
OPT_OUT = {
    'es': {'PARAR', 'PARA', 'ALTO', 'DETENER', 'CANCELAR', 'BAJA', 'DESUSCRIBIR'},
    'tl': {'TIGIL', 'HINTO', 'ITIGIL'},
    'hmn': {'TSEEM', 'NRES'},
}
```

`normalize(body)`:

1. Strip leading and trailing whitespace.
2. NFKD-normalize and drop combining marks.
3. Uppercase.
4. Strip trailing punctuation (`.!?`).
5. Collapse internal whitespace.

Matching is exact on the whole normalized body. A message that merely contains "stop"
("please stop by") is not an opt-out.

`classify(body) -> ('twilio_opt_out' | 'opt_out' | 'twilio_opt_in' | None, language | None)`

## 3. Inbound webhook (`camp/apps/accounts/views.py` → `TwilioInboundSMS`)

- **Route.** `POST webhooks/twilio/inbound/` (named `twilio-inbound-sms`), `csrf_exempt`,
  wired in `camp/urls.py` next to the status callback.
- **Signature.** Validated with `RequestValidator(settings.TWILIO_AUTH_TOKEN)` exactly
  like `TwilioStatusCallback`; 403 when invalid.
- **Lookup.** Exact match on `User.phone == From` (E.164). No match: return an empty
  `<Response/>` with status 200.
- **Actions by classification:**

  | Classification | `phone_verified` | `sms_blocked` | Reply |
  |---|---|---|---|
  | `twilio_opt_out` | set False | set True | none (Twilio sends its own confirmation) |
  | `opt_out` | set False | unchanged | one TwiML `<Message>` (see below) |
  | `twilio_opt_in` | unchanged | set False | none (Twilio's own reply) |
  | none | unchanged | unchanged | empty `<Response/>` |

  - For `twilio_opt_in`, phone verification stays false: the user re-verifies on the site.
  - The `opt_out` reply is in the user's `language`, from the copy in §6, falling back
    to English.
- **Content type.** `text/xml` on every response. Writes use `update_fields`.

## 4. Send-side handling

- **Alerts** (`camp/apps/alerts/tasks.send_alert_notification`): when Twilio raises a
  `TwilioRestException` with `code == 21610`, the notification is marked FAILED as
  today, and the user is set to `phone_verified=False, sms_blocked=True`.
- **Verification codes and other account texts** (`camp/apps/accounts/tasks.send_sms_message`):
  catch the 21610 `TwilioRestException` and set the same two fields on the user with
  that phone. The task is async, so this is bookkeeping only. Other exceptions behave as
  they do today.
- **Pre-send guard.** `User.send_sms()` returns False without enqueuing when
  `sms_blocked` is True. This covers verification codes too.

## 5. Re-verification UX

When a user with `sms_blocked=True` asks for a verification code, the request fails
with a clear error instead of silently doing nothing. The places that send codes:

- `SendPhoneVerificationEndpoint` (v1, v2);
- the signup and password-reset forms in `camp/api/v{1,2}/accounts/forms.py`;
- `camp/apps/accounts/forms.py` and `views.py`.

They check `user.sms_blocked` before calling `send_phone_verification_code()` and raise
a validation error:

> Text START to {number} to allow texts from SJVAir again, then request a new code.

`{number}` is the formatted `TWILIO_PHONE_NUMBERS[0]`.

One exception: password reset by phone must not reveal whether an account exists. Its
form already returns the same response for an unknown phone, so for a blocked user it
sends nothing and returns the normal response. The message only appears in
authenticated flows.

## 6. Reply copy (opt-out confirmation, non-Twilio keywords)

- `en`: `SJVAir: You won't get any more texts from us. To get alerts again, verify your phone at https://www.sjvair.com/account/`
- `es`: `SJVAir: Ya no recibirá mensajes de nosotros. Para volver a recibir alertas, verifique su teléfono en https://www.sjvair.com/account/`
  - It goes out as GSM-7 after `sms_safe`-style ASCII folding of the accents.
- `tl`, `hmn`: English until vetted translations exist.

## 7. Twilio configuration (manual, Derek)

On the production number, set "A message comes in" to
`https://www.sjvair.com/webhooks/twilio/inbound/` (HTTP POST). Until that's done, §4
still catches English opt-outs on the next send.

## Testing

- **Keywords:** normalization (case, accents, whitespace, trailing punctuation), and
  each language's keywords classify correctly. Containing "stop" inside a sentence is
  not an opt-out.
- **Webhook:**
  - Signature is validated (403).
  - Unknown sender returns 200 with an empty response.
  - English STOP sets unverified and blocked, with no reply body.
  - Spanish PARAR sets unverified only and returns a Spanish `<Message>`.
  - START clears blocked and leaves the phone unverified.
  - A non-keyword text changes nothing.
- **Sends:**
  - A 21610 on the alert send marks the user unverified and blocked.
  - A 21610 on `send_sms_message` does the same.
  - `send_sms()` doesn't enqueue for a blocked user.
  - An opted-out user is excluded from alert recipients.
- **Verification:** a blocked user requesting a code gets the "text START" error from
  the v1/v2 endpoints, and password reset stays non-revealing.
