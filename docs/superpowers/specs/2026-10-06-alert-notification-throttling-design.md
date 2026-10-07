# Alert Notification Throttling — Design Spec

**Date:** 2026-10-06
**Status:** Approved (Derek, 2026-10-06)
**Builds on:** `2026-07-09-notifications-redesign-design.md` (PR #246). This spec
replaces that spec's §3 "Evaluator anti-flapping logic" and changes when
`notify_subscribers` runs. The `Notification` audit log, Twilio send task, delivery
webhook and sqids migration from that spec are kept.

## Why

An audit of PR #246 (2026-10-06) simulated 24h of realistic PM2.5 traces through the
real evaluator, every 10 minutes, for one subscriber at "Unhealthy for Sensitive
Groups". It sent 8–27 texts per day per monitor, each 4 billed SMS segments. The
per-alert 30-minute cooldown doesn't stop it, for three reasons:

- A drop to a lower level isn't texted, but the next rise back re-texts everyone.
- Each closed-then-reopened alert starts fresh.
- The 2-rank bypass lets Moderate↔Unhealthy flapping skip the cooldown entirely.

For comparison, the Valley Air District sent one subscriber 167 alerts from June 2024
to October 2026: never more than 3 a day, never less than 1 hour apart, and same-level
repeats at least 2 hours apart. They text only when the level rises, never on
improvement, and send no all-clear.

The audit also found two bugs that block deploying #246:

- `periodic_alerts` never evaluates monitors without alert history.
  `exclude(alerts__end_time__isnull=True)` also excludes monitors with no alerts. After
  the destructive `Alert` migration, that's every monitor.
- The Twilio `status_callback` points at `https://sjvair.com`. That is a Squarespace
  301 to `http://www.sjvair.com`, so no delivery callback ever reaches Django.

## Goals

- Stay near real time: evaluate every 10 minutes.
- Text a subscriber only when the air at their monitor gets worse than what they were
  last told.
- Never text about improvement, and send no all-clear.
- At most one text per 2 hours per subscription, unless the level jumps 2+ ranks.
- Re-arm a subscription only after a sustained (2-hour) period below its threshold.
- A daily 10 AM Pacific "still bad" reminder during multi-day events.
- Short, GSM-7-only messages: at most 2 SMS segments, down from 4.
- Fix the scheduler and webhook-domain bugs.

## Non-Goals

- Twilio STOP / opt-out handling (error 21610). Follow-up. A sticky sender isn't needed:
  production has a single Twilio number.
- Restricting `Subscription.level` choices. `good` and `moderate` subscriptions stay
  valid. In practice they behave as `moderate`, because no alert record exists below
  Moderate (see §3).
- Per-user caps across monitors. The user chose per-subscription limits.
- Changing which calibration alerts read: still `PM25_UnivariateLinearRegression` for
  PurpleAir/AirGradient. Production writes those every ~2 minutes (verified via the
  public API, 2026-10-06).

---

## 1. Level computation (`camp/apps/alerts/evaluator.py`)

One window for everything: **the trailing 60 minutes**. At 4:10 that is 3:10–4:10.

- **Average path:** the average of alert-stage entries with `now - 60m <= timestamp <= now`.
  - Return `None` unless the window holds at least
    `ceil((60m / interval) * MIN_COVERAGE)` entries (minimum 1), with `MIN_COVERAGE = 0.5`.
  - PurpleAir (2-minute interval) needs ≥ 15 entries; AirGradient (1-minute) needs ≥ 30.
  - This stops a single reading, or a mostly-offline hour, from deciding the level.
- **Current-level path:** used when the alert stage's interval is ≥ 60 minutes (hourly
  monitors). Take the latest entry with `timestamp <= now`. Return `None` if it's older
  than 2× the interval (the existing staleness fix).
- **Per-stage interval:** "interval" is the alert stage's cadence. It defaults to
  `monitor.EXPECTED_INTERVAL` and can be overridden by an optional `'expected_interval'`
  key in the `ENTRY_CONFIG[...]['alerts']` dict. That key is stripped out before the
  dict is used as queryset lookup kwargs.
  - AQLite gets `'expected_interval': '1h'`. Its calibrated O3 is an hourly aggregate,
    even though raw data arrives every 5 minutes.
- **Return value:** `AlertEvaluator.get_levels()` returns
  `{entry_model: Level | None}` without touching the DB.
- **`evaluate()`:** updates `Alert`/`AlertUpdate` records from those levels and returns
  the same dict.

## 2. Alert records

`Alert`/`AlertUpdate` are now a record of events only. They no longer send anything.

- **Creation:** create an alert when the level is ≥ Moderate, there's no open alert for
  that `(monitor, entry_type)`, and the monitor is active.
- **Updates:** record an update whenever the level differs from the alert's latest
  update, in either direction.
- **Closing:** close the alert, recording a final Good update, when the level is Good
  and the alert is at least `MINIMUM_DURATION` (60m) old.
- **No data:** a `None` level changes nothing.
- **Notifications:** `Alert.create_update()` no longer calls `notify_subscribers`.
- **Timestamps:** `create_update()` sets `timestamp` explicitly to `timezone.now()`.
- **Removed:** `ESCALATION_WINDOW`, `DEESCALATION_WINDOW`, `NOTIFICATION_COOLDOWN` and
  `SEVERITY_BYPASS_RANKS`.
- **One open alert:** a partial unique constraint allows only one open alert per
  `(monitor, entry_type)`.

## 3. Subscriber notification rules (`camp/apps/alerts/notifications.py`)

**Monitor level.** The worst level across the monitor's alertable pollutants, compared
by rank. The pollutant with that level is the *driving* pollutant. If every pollutant's
level is `None`, nothing changes this tick.

**Per-subscription state.** Three new nullable fields on `Subscription`:

- `last_notified_level` (blank = re-armed)
- `last_notified_at`
- `below_threshold_since`

**Each 10-minute tick**, for each subscription on the monitor, with `level` = the
monitor level and `threshold` = the subscription's level:

1. If `level < threshold`:
   - Set `below_threshold_since` if it's unset.
   - If it has been set for ≥ `RESET_AFTER` (2h), clear `last_notified_level`. This is
     the re-arm.
   - Send nothing.
2. Otherwise:
   - Clear `below_threshold_since`.
   - If `last_notified_level` is set and `level <= last_notified_level`, send nothing.
     Improvements and repeats are never texted.
   - If `last_notified_at` is within `MIN_INTERVAL` (2h), send only if
     `level.rank - last_notified_level.rank >= BYPASS_RANKS` (2).
   - **Daily cap** (added 2026-10-06 after the final review): if the subscription
     has already received `DAILY_CAP` (3) alert-kind texts since local (Pacific)
     midnight, send only if the rise is ≥ `BYPASS_RANKS` above the last text.
     Reminders don't count toward the cap. Without the cap, episodic smoke
     (40 min on, 140 min off) re-armed every plume and sent 8 texts a day.
   - Otherwise send `level`.
3. **On send:**
   - Create a `Notification(kind=ALERT, level=level.key, alert_update=<open alert for
     the driving pollutant>.latest)`.
   - Set `last_notified_level = level` and `last_notified_at = now`.
   - Enqueue the send on commit, as today.
   - If no open alert exists for the driving pollutant, don't send and leave
     `last_notified_*` untouched. This can't happen when the level is ≥ Moderate,
     because the evaluator runs first in the same tick. It's logged as a warning.

**Consequences:**

- A rise that's too small, inside the 2-hour window, isn't lost. It's re-checked every
  tick and sent once the window opens, if the trailing-hour level is still higher.
- Same-level re-texts are always > 2h apart.

**Who is eligible.** Recipients come from `get_recipients(monitor)`:

- the user has a verified, non-empty phone;
- `settings.SEND_SMS_ALERTS` is on. If it's off, the whole step is skipped and no state
  changes.

**Locking.** Subscription rows are locked (`select_for_update(of=('self',))`) inside one
transaction per monitor. A concurrent reminder and alert can't both send.

## 4. Daily reminder

**When.** A periodic task fires at `crontab(minute='0', hour='17,18')`. Huey crontabs
run in UTC, so that covers 10 AM PDT and PST. It proceeds only when
`camp.utils.datetime.localtime().hour == 10`.

**What it does.** For each monitor with at least one subscription whose
`last_notified_level` is set, it computes `get_levels()` and the monitor level. A
subscription gets a reminder when all of these hold:

- `last_notified_level` is set (not re-armed);
- the level is ≥ threshold;
- `last_notified_at` is before local midnight today, i.e. no text yet today for this
  monitor.

**On send:**

- `Notification(kind=REMINDER)` with the current level, which may be lower than the
  last-notified level.
- Set `last_notified_level` = the current level and `last_notified_at = now`.
- The reminder counts toward the 2-hour limit.

## 5. Scheduler (`camp/apps/alerts/tasks.py`)

**`periodic_alerts`** (every 10 minutes), under
`get_queue('primary').lock_task('periodic-alerts')`:

- Iterates `get_alert_monitors()`: active monitors of every subclass that has alertable
  entry types, plus any monitor with an open alert, each exactly once.
- For each: `levels = AlertEvaluator(monitor).evaluate()`.
- Then `notifications.notify_subscribers(monitor, levels)`, if the monitor has
  subscriptions.

## 6. Message format

GSM-7 only (no emoji). At most 2 segments (306 chars) for a 40-character monitor name.

```
SJVAir alert: Air quality is Unhealthy for Sensitive Groups (PM2.5) at Fresno - Garland.
Sensitive groups should stay indoors and avoid outdoor activities.
https://www.sjvair.com/monitor/<id>
```

The reminder's first line is
`SJVAir: Air quality is still {level} ({pollutant}) at {name}.`

The send task's `status_callback` uses `https://www.sjvair.com`.

## 7. Data model changes

- **`Subscription`:** `last_notified_level` (CharField 25, blank), `last_notified_at`
  (DateTime, null), `below_threshold_since` (DateTime, null). Existing rows get
  blank/null: armed, no history.
- **`Notification`:** `kind` (`alert` | `reminder`, default `alert`), `level`
  (CharField 25, blank).
- **`Alert`:** partial `UniqueConstraint(fields=['monitor', 'entry_type'],
  condition=Q(end_time__isnull=True), name='one_open_alert_per_monitor_entry_type')`.
  Safe to add: the earlier migration 0006 empties the table.

## 8. Feature flag (trial rollout)

Alert and reminder texts are limited to selected users by the django-waffle flag
`sms_alerts`, created by alerts migration 0009 with **Everyone: Unknown**.

- **Where it sits:** `process_subscriptions`, the shared path of `notify_subscribers`
  and `send_reminders`. The flag is read once per call; a subscriber it is off for is
  skipped before the rule runs: no text, no `Notification`, no state change, no save.
- **Who gets texts:** users added to the flag (or in a group on it), staff/superusers
  per the flag's checkboxes (Superusers is on by default), or everyone when
  Everyone is Yes. Everyone: No turns it off for all, even listed users. A missing
  flag texts no one.
- **What it does not gate:** verification codes, account texts and the STOP webhook.
- **Broadening:** edit the flag in the Django admin (Waffle > Flags). No deploy.
- **Caveat:** unflagged subscriptions stay armed (blank `last_notified_level`) for the
  whole trial. Broadening to everyone therefore causes the same first-tick burst as a
  fresh deploy: every subscriber currently at or above their threshold is texted at
  once. Broaden on a clean-air day.

## Acceptance

`camp/apps/alerts/test_scenarios.py` replays the audit scenarios through the real
evaluator, notification rules and reminder task, with a patched clock. For one
subscriber at USG:

- **Spacing:** two consecutive texts are never < 2h apart, unless the second is ≥ 2
  ranks above the first.
- **Volume:** no 24h period has more than 4 texts.
- **Episodic smoke:** 40 min at 60 µg/m³ then 140 min clean, repeated for 24h, sends
  at most 3 alert texts per Pacific day.
- **Faulty sensor:** one 400 µg/m³ reading per hour on clean air sends **0** texts.
- **Multi-day smoke:** 72h at a constant Unhealthy sends exactly 1 alert, plus one
  reminder per 10 AM passed.
- **Daily peaks:** 4 days of afternoon peaks (4h at Unhealthy, then clean) re-arm
  overnight. Each day gets at least 1 and at most 2 texts (USG, then Unhealthy 2h
  later), and no reminders.
