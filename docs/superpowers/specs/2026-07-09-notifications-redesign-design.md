# Notifications (Alerts) System Redesign — Design Spec

**Date:** 2026-07-09
**Status:** Approved

## Overview

The `alerts` app (`Subscription`, `Alert`, `AlertUpdate`, `AlertEvaluator`) drives SJVAir's threshold-based air quality notifications. It has two problems in practice:

1. **No observability into delivery.** SMS sending is a model method (`Alert.send_notifications`) that loops over subscribers and calls Twilio inline, with no record of who was notified, when, or whether it succeeded. `TwilioRestException` is imported but never caught, so failures are silently swallowed.
2. **No protection against notification flapping.** `AlertEvaluator.update_check` creates a new `AlertUpdate` (and fires a notification) any time the computed level differs from the last update, with no minimum time between updates. A monitor's average hovering near a threshold boundary can produce a notification on every 10-minute evaluation cycle.

This redesign adds a persisted delivery log, decouples sending from the `Alert` model, and hardens `AlertEvaluator` against flapping using asymmetric escalate/de-escalate windows plus a notification cooldown.

## Goals

- Record every notification attempt (who, which alert update, status, error, provider message ID) in a queryable audit trail
- Move SMS-sending logic out of the `Alert` model into its own module, with recipient resolution behind a single named function
- Actually catch and log Twilio failures instead of letting them vanish
- Escalate quickly (15-minute average), de-escalate/close slowly (60-minute average, unchanged from today) to reduce flapping
- Add a minimum gap between consecutive notifications on the same alert, bypassed for large severity jumps
- Fix a real staleness bug in `AlertEvaluator.get_current_level` (docstring claims a freshness check that was never implemented), relevant to hourly-reporting monitors like AirNow/BAM
- Remove dead code left over from when the system was PM2.5-only

## Non-Goals

- No notification channel abstraction. SMS via Twilio is the only channel in use or planned; no `channel` field, no interface.
- No regional subscriptions. `Region` (`camp/apps/regions/`) already supports geometry-based monitor lookup and could support "subscribe to all monitors in this region" later, but that's not built here. The only accommodation made now is that recipient resolution lives behind one function (`get_recipients`) instead of an inline queryset, so that extension doesn't require touching the rest of the pipeline.
- No changes to `Subscription` (model, API endpoints, or admin). Existing subscriptions and their semantics (user + monitor + level, not pollutant-specific) are preserved as-is.
- No changes to per-pollutant alert evaluation. `Alert`/`AlertEvaluator` already operate per `(monitor, entry_type)` pair, and multiple alertable pollutants per monitor (e.g., AirNow's PM2.5 and O3) already produce independent `Alert` records that independently notify subscribers. This already works and isn't being changed — see "Multi-pollutant behavior" below.

---

## 1. Notification audit log

### New model: `camp/apps/alerts/models.py`

```python
class Notification(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = 'queued', _('Queued')
        SENT = 'sent', _('Sent')
        DELIVERED = 'delivered', _('Delivered')
        UNDELIVERED = 'undelivered', _('Undelivered')
        FAILED = 'failed', _('Failed')

    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.Notification'))

    alert_update = models.ForeignKey('alerts.AlertUpdate', related_name='notifications', on_delete=models.CASCADE)
    subscription = models.ForeignKey('alerts.Subscription', null=True, blank=True, related_name='notifications', on_delete=models.SET_NULL)
    user = models.ForeignKey('accounts.User', related_name='notifications', on_delete=models.CASCADE)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    message = models.TextField()
    provider_id = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
```

- Uses `SqidsField` (`django_sqids`), not `SmallUUIDField` — per project convention, newer models use sqids over the legacy smalluuid PK pattern (see `regions`, `pesticides`, `ceidars` apps). Primary key remains the default auto `id`; `sqid` is the external-facing identifier, looked up via `provider_id`/`MessageSid` internally rather than `sqid` for the webhook.
- `subscription` is `SET_NULL` so the audit trail survives the user unsubscribing later.
- `user` is `CASCADE` (consistent with `Subscription.user`) — if the account is deleted, its notification history goes with it.
- `message` stores the exact rendered text sent, independent of what the `Alert`/`AlertUpdate` looks like later.
- No `channel` field (see Non-Goals).

### New module: `camp/apps/alerts/notifications.py`

- `get_recipients(alert)` — returns the `Subscription` queryset for an alert. Today: `Subscription.objects.filter(monitor_id=alert.monitor_id).select_related('user')`, unchanged from current behavior. This is the one seam for future regional subscriptions.
- `notify_subscribers(alert_update)` — replaces `Alert.send_notifications`. Preserves the existing `settings.SEND_SMS_ALERTS` global kill switch as an early return (unchanged behavior: when the flag is off, nothing is sent and no `Notification` rows are created — this is a hard bypass, not an audited skip). Otherwise, builds the message text (same content as today), iterates `get_recipients(alert)`, and for each subscriber whose `level` threshold is met:
  - Creates a `Notification(status=QUEUED, message=...)`
  - Enqueues a Huey task to actually send it

### New task: `camp/apps/alerts/tasks.py` — `send_alert_notification(notification_id)`

- Loads the `Notification`, sends via the existing Twilio client pattern (same as `accounts.tasks.send_sms_message`)
- On success: `status=SENT`, `sent_at=now()`, `provider_id=<Twilio SID>`. The `messages.create()` call includes `status_callback=<webhook URL>` (see below) so delivery confirmation arrives asynchronously rather than by polling.
- On `TwilioRestException`: `status=FAILED`, `error=str(exception)` — caught and logged instead of propagating

### Delivery status webhook: `camp/apps/alerts/views.py` — `TwilioStatusCallback`

Twilio POSTs to this endpoint as a message's status changes after sending (`sent` → `delivered`/`undelivered`, or `failed`). It's wired at the top level (`camp/urls.py`, e.g. `webhooks/twilio/status/`), not under `account/`, since it's an external callback rather than a user-facing page — same `csrf_exempt` treatment as the existing `CreateEntry` upload endpoint in `api/v2/monitors/endpoints.py`.

- Validates the request using `twilio.request_validator.RequestValidator(settings.TWILIO_AUTH_TOKEN)` against the `X-Twilio-Signature` header; rejects with 403 if invalid. No other Twilio-originated endpoint currently exists in the codebase, so there's no established pattern to follow here — just Twilio's own documented validation method.
- Reads `MessageSid` and `MessageStatus` from the POST body. Maps Twilio's `delivered`/`undelivered`/`failed` to the matching `Notification.Status`; other intermediate statuses (`queued`, `sending`, `sent`) are ignored since `SENT` is already recorded at send time.
- Looks up `Notification.objects.get(provider_id=MessageSid)`. If no match (e.g., a stale or replayed callback), returns 200 without error — Twilio doesn't need a failure response for this case.
- The callback URL follows the existing convention of hardcoding the production domain (see `Alert.send_notifications`'s `https://sjvair.com{...}` today) rather than introducing a new `SITE_URL` setting.

### Changes to `Alert` (`models.py`)

- `create_update()` calls `notifications.notify_subscribers(update)` instead of `self.send_notifications(update.get_level())`
- `send_notifications()` method removed (moved to `notifications.py`)
- `get_average()` method removed — dead code, hardcodes `Avg('pm25')`, has zero callers anywhere in the codebase (confirmed via grep). Leftover from the PM2.5-only era; `AlertEvaluator` has its own generic per-entry-model averaging and never called this method.

---

## 2. Evaluator anti-flapping logic

### Window changes (`camp/apps/alerts/evaluator.py`)

- `ESCALATION_WINDOW = 15m` (replaces `CREATION_WINDOW`, used for both creating a new alert and escalating an active one — i.e., level rank increasing)
- `DEESCALATION_WINDOW = 60m` (same value as today's `UPDATE_WINDOW`, now explicitly used for level rank decreasing, including closing)
- `MINIMUM_DURATION = 60m` (unchanged — alert must be at least this old before it can close)
- `NOTIFICATION_COOLDOWN = 30m` (new)
- `SEVERITY_BYPASS_RANKS = 2` (new — a level change of 2 or more ranks always bypasses the cooldown)

### `update_check` restructure

For an active alert:

1. Compute `fast_level` using `ESCALATION_WINDOW` and `slow_level` using `DEESCALATION_WINDOW` (both go through the existing `get_level()` interval-aware fallback — see below).
2. If `fast_level` outranks the current level → escalation candidate.
3. Elif `slow_level` is a lower rank than the current level (including `GOOD`) → de-escalation candidate.
4. Else → no change.
5. If the candidate is `GOOD`: apply existing `MINIMUM_DURATION` gate before closing (unchanged behavior — if the alert isn't old enough yet, do nothing, no notification).
6. Otherwise (non-GOOD candidate, either direction): check the cooldown — if less than `NOTIFICATION_COOLDOWN` has passed since the last update **and** the rank jump is less than `SEVERITY_BYPASS_RANKS`, suppress (no update, no notification). Otherwise create the update.

Cooldown and bypass are evaluated per-`Alert`, not per-monitor or per-user — see "Multi-pollutant behavior" below for why that matters.

### Hourly-monitor handling

`get_level()` already falls back to `get_current_level()` (single latest reading, no averaging) whenever the monitor's `EXPECTED_INTERVAL` is >= the requested window — this is required because you can't compute a meaningful 15-minute average from a monitor that reports once an hour. This fallback already applies correctly to both the new `ESCALATION_WINDOW` and `DEESCALATION_WINDOW` for monitors like AirNow (`EXPECTED_INTERVAL = '1 hour'`), so no special-casing is needed for the window split itself.

However, `get_current_level()`'s docstring claims stale entries (more than 2x the expected interval old) are ignored, but the implementation never actually checks this — it returns whatever the most recent entry is, however old. Fixed as part of this work:

```python
def get_current_level(self, entry_model, lookup):
    entry = (entry_model.objects
        .filter(monitor_id=self.monitor.pk, **lookup)
        .order_by('-timestamp')
        .first()
    )
    if not entry:
        return None

    interval = pd.to_timedelta(self.monitor.EXPECTED_INTERVAL)
    if timezone.now() - entry.timestamp > interval * 2:
        return None

    return entry_model.Levels.get_level(entry.value)
```

This matters most for hourly monitors, since they lean on this fallback for every evaluation.

### Multi-pollutant behavior (no change, documented for clarity)

`Alert`/`AlertEvaluator` already operate per `(monitor, entry_type)` pair — `monitor.alertable_entry_types` returns every alertable pollutant (e.g., AirNow already alerts on both `PM25` and `O3`), and each gets its own independent `Alert`/`AlertUpdate` chain. `Subscription` was never scoped to a pollutant — it's `user + monitor + level` — so a subscriber already gets notified regardless of which pollutant crossed their threshold. This already works today and isn't being changed.

The one thing to get right: since cooldown is scoped per-`Alert` (not per-monitor or per-user), a real PM2.5 exceedance and a real O3 exceedance on the same monitor around the same time correctly produce two independent notifications — one alert's cooldown never suppresses another's.

---

## Testing

Extend `camp/apps/alerts/tests.py`:

- Cooldown suppresses a rapid re-escalation within the window
- Severity bypass (2+ rank jump) fires immediately despite an active cooldown
- 15m/60m split produces different escalate vs. de-escalate outcomes than a single shared window would
- `get_current_level` returns `None` for a stale entry beyond `2x EXPECTED_INTERVAL`
- Two alertable entry types on one monitor (PM25 + O3) produce independent notifications, unaffected by each other's cooldown

New tests for `camp/apps/alerts/notifications.py` (mocked Twilio client):

- Successful send creates a `Notification` with `status=SENT`, `provider_id` populated
- `TwilioRestException` is caught, not raised — `Notification` ends up `status=FAILED` with `error` populated
- Only subscribers whose `level` threshold is met receive a `Notification`

New tests for `TwilioStatusCallback`:

- Valid signature + `MessageStatus=delivered` updates the matching `Notification` to `DELIVERED`
- Valid signature + `MessageStatus=undelivered` updates to `UNDELIVERED`
- Invalid/missing signature is rejected with 403 and does not touch any `Notification`
- Unknown `MessageSid` returns 200 without error and without modifying any row

## Migration

One new migration for the `Notification` model. No changes to existing `Subscription`, `Alert`, or `AlertUpdate` schemas.
