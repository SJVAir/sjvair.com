# Alert Notification Throttling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop alert texts from spamming subscribers and inflating the Twilio bill, while
still evaluating air quality every 10 minutes. Also fix the two deploy blockers found in
the PR #246 audit.

**Architecture:**

- `AlertEvaluator` computes one trailing-60-minute level per pollutant, with a
  minimum-readings rule. It keeps `Alert`/`AlertUpdate` as a record only.
- A per-`Subscription` state machine in `notifications.py` decides who gets texted.
  Rules: escalation only, a 2h limit per subscription with a 2-rank bypass, and a re-arm
  after 2h below the subscriber's threshold.
- A 10 AM Pacific task sends one "still bad" reminder per subscription per day.
- The scheduler evaluates each relevant monitor exactly once per run, under a lock.

**Tech Stack:** Django 5 / PostGIS, django-huey (`db_periodic_task`, `get_queue().lock_task`),
pandas `Timedelta`, Twilio REST client, pytest + `django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-10-06-alert-notification-throttling-design.md`
(read it before starting any task). It builds on
`docs/superpowers/specs/2026-07-09-notifications-redesign-design.md`.

## Global Constraints

- **Location.** All work happens in the worktree
  `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/notifications-redesign`, on branch
  `feature/alerts-redesign`.
  - Your first action in every task: `cd` there and confirm with
    `git rev-parse --show-toplevel && git branch --show-current`.
  - Never touch the main checkout at `/home/derek/dev/ccac/sjvair.com`.
- **Do not commit. Do not push.** Leave all changes in the working tree; Derek commits
  when he says so. Never `git add -A`.
- **Test command (TEST below).** Run from the worktree. The worktree has no `.env.test`;
  this uses the main checkout's compose file with the worktree bind-mounted and a private
  DB name:
  ```
  docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_alerts -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/notifications-redesign:/app test pytest <PATHS> -q -p no:cacheprovider --create-db
  ```
  - The line `fatal: not a git repository` in its output is harmless.
  - The management command form is the same, with `test python manage.py <cmd>` in place
    of `test pytest ...`.
- **Test style.** `django.test.TestCase`, Django fixtures (`users.yaml`, `purple-air.yaml`),
  plain `assert` (never `self.assertX`), `pytest.raises` for exceptions.
- **Model fields.** The verbose name is the first positional arg:
  `models.DateTimeField(_('Label'), null=True)`. Don't align `=` signs.
- **Huey tasks in tests.** Call periodic/db tasks with `.call_local()`; a bare call returns
  a `Result` wrapper.
- **Constants, exact values:**
  - `AlertEvaluator.WINDOW = pd.Timedelta('60m')`
  - `AlertEvaluator.MINIMUM_DURATION = pd.Timedelta('60m')`
  - `AlertEvaluator.MIN_COVERAGE = 0.5`
  - `notifications.MIN_INTERVAL = timedelta(hours=2)`
  - `notifications.BYPASS_RANKS = 2`
  - `notifications.RESET_AFTER = timedelta(hours=2)`
  - `notifications.REMINDER_HOUR = 10`
- **SMS copy.** GSM-7 characters only (no emoji). Links use `https://www.sjvair.com`,
  never the apex `https://sjvair.com` (it's a Squarespace 301).
- **Timezone.** The project TZ is UTC. Local-time logic uses
  `camp.utils.datetime.localtime()` (America/Los_Angeles).

## Review Focus

1. **DST:** the reminder must fire at 10 AM local in both PDT (17:00 UTC) and PST
   (18:00 UTC), and only once a day. Tests in Task 4.
2. **The driving pollutant isn't PM2.5:** O3 at USG while PM2.5 is Moderate. The text
   must cite Ozone and link the O3 alert's update. Test in Task 3.
3. **An alert closes and reopens while the subscription hasn't re-armed:** no new text.
   Test in Task 3.
4. **The monitor goes offline (all levels `None`):** subscription state must not change,
   and nothing is sent. Test in Task 3.
5. **An hourly alert stage on a fast monitor (AQLite O3):** the minimum-readings rule
   must not silence it. Test in Task 1.

---

### Task 1: Trailing-hour levels in `AlertEvaluator`; alert records stop sending

**Files:**
- Modify: `camp/apps/alerts/evaluator.py` (full rewrite below)
- Modify: `camp/apps/alerts/models.py:89-97` (`Alert.create_update`)
- Modify: `camp/apps/monitors/aqlite/models.py:70` (alerts config)
- Test: `camp/apps/alerts/tests.py`
  - replace classes `AlertEvaluatorTests` and `MultiPollutantAndHourlyMonitorTests`;
  - delete class `NotifySubscribersTests` (Task 3 re-adds a new one).

**Interfaces:**
- **Produces:**
  - `AlertEvaluator.split_config(config: dict) -> tuple[dict, str | None]` (staticmethod)
  - `AlertEvaluator.get_levels() -> dict[EntryModel, Level | None]`
  - `AlertEvaluator.evaluate() -> dict[EntryModel, Level | None]`
  - `AlertEvaluator.get_level(entry_model, lookup, interval=None) -> Level | None`
  - `Alert.create_update(level, timestamp=None) -> AlertUpdate` (no longer notifies)
- **Consumes:** nothing new.

- [ ] **Step 1: Write the failing tests**

In `camp/apps/alerts/tests.py`, replace the whole `AlertEvaluatorTests` class and the whole
`MultiPollutantAndHourlyMonitorTests` class with the code below. Delete the whole
`NotifySubscribersTests` class. Leave `NotificationModelTests` and
`TwilioStatusCallbackTests` untouched. The existing imports at the top of the file already
cover everything used here.

```python
class AlertEvaluatorTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.monitor.is_active = True
        self.lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]

    def create_pm25_entry(self, value, minutes_ago=0):
        return PM25.objects.create(
            monitor=self.monitor,
            value=value,
            timestamp=timezone.now() - timedelta(minutes=minutes_ago),
            **self.lookup
        )

    def fill_hour(self, value, count=30):
        # One reading every 2 minutes (PurpleAir's cadence) across the trailing hour.
        for i in range(count):
            self.create_pm25_entry(value, minutes_ago=i * 2)

    def level(self):
        return AlertEvaluator(self.monitor).get_levels()[PM25]

    def test_level_is_trailing_hour_average(self):
        self.fill_hour(40)
        assert self.level() == AQLevel.scale.UNHEALTHY_SENSITIVE

    def test_readings_older_than_an_hour_are_ignored(self):
        self.fill_hour(5)
        for i in range(30):
            self.create_pm25_entry(200, minutes_ago=61 + i)
        assert self.level() == AQLevel.scale.GOOD

    def test_future_readings_are_ignored(self):
        self.fill_hour(5)
        self.create_pm25_entry(500, minutes_ago=-10)
        assert self.level() == AQLevel.scale.GOOD

    def test_level_is_none_below_min_coverage(self):
        self.fill_hour(40, count=14)
        assert self.level() is None

    def test_level_counts_at_min_coverage(self):
        self.fill_hour(40, count=15)
        assert self.level() == AQLevel.scale.UNHEALTHY_SENSITIVE

    def test_single_spike_cannot_reach_unhealthy_for_sensitive_groups(self):
        self.fill_hour(6, count=29)
        self.create_pm25_entry(400, minutes_ago=1)
        assert self.level() < AQLevel.scale.UNHEALTHY_SENSITIVE

    def test_split_config_strips_expected_interval(self):
        lookup, interval = AlertEvaluator.split_config({'stage': 'calibrated', 'expected_interval': '1h'})
        assert lookup == {'stage': 'calibrated'}
        assert interval == '1h'

    def test_expected_interval_override_uses_latest_reading(self):
        # One reading fails the coverage rule at the monitor's 2-minute
        # cadence, but an hourly alert stage reads the latest entry instead.
        self.create_pm25_entry(40, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        assert evaluator.get_level(PM25, self.lookup, '1h') == AQLevel.scale.UNHEALTHY_SENSITIVE
        assert evaluator.get_level(PM25, self.lookup) is None

    def test_aqlite_alert_stage_is_hourly(self):
        from camp.apps.monitors.aqlite.models import AQLite
        config = AQLite.alertable_entry_types[O3]
        lookup, interval = AlertEvaluator.split_config(config)
        assert interval == '1h'
        assert 'expected_interval' not in lookup

    def test_evaluate_creates_alert_at_moderate_or_above(self):
        self.fill_hour(40)
        levels = AlertEvaluator(self.monitor).evaluate()
        assert levels[PM25] == AQLevel.scale.UNHEALTHY_SENSITIVE

        alert = Alert.objects.get(monitor=self.monitor)
        assert alert.entry_type == PM25.entry_type
        assert alert.updates.count() == 1
        assert alert.latest == alert.updates.first()

    def test_evaluate_skips_good(self):
        self.fill_hour(5)
        AlertEvaluator(self.monitor).evaluate()
        assert Alert.objects.count() == 0

    def test_evaluate_skips_inactive_monitor_with_no_alert(self):
        self.monitor.is_active = False
        self.fill_hour(100)
        AlertEvaluator(self.monitor).evaluate()
        assert Alert.objects.count() == 0

    def test_evaluate_records_every_level_change(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        PM25.objects.all().delete()
        self.fill_hour(20)  # MODERATE: drops are recorded too
        AlertEvaluator(self.monitor).evaluate()

        alert = Alert.objects.get(monitor=self.monitor)
        levels = [update.get_level() for update in alert.updates.order_by('timestamp', 'pk')]
        assert levels == [AQLevel.scale.UNHEALTHY_SENSITIVE, AQLevel.scale.MODERATE]

    def test_evaluate_no_update_when_level_unchanged(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        AlertEvaluator(self.monitor).evaluate()
        assert AlertUpdate.objects.count() == 1

    def test_evaluate_closes_alert_after_minimum_duration(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        alert = Alert.objects.get(monitor=self.monitor)
        Alert.objects.filter(pk=alert.pk).update(start_time=timezone.now() - timedelta(minutes=61))

        PM25.objects.all().delete()
        self.fill_hour(5)
        AlertEvaluator(self.monitor).evaluate()

        alert.refresh_from_db()
        assert alert.end_time is not None
        assert alert.updates.latest().get_level() == AQLevel.scale.GOOD

    def test_evaluate_keeps_young_alert_open(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        PM25.objects.all().delete()
        self.fill_hour(5)
        AlertEvaluator(self.monitor).evaluate()

        alert = Alert.objects.get(monitor=self.monitor)
        assert alert.end_time is None
        assert alert.updates.count() == 1

    def test_evaluate_ignores_missing_data_on_open_alert(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        PM25.objects.all().delete()
        AlertEvaluator(self.monitor).evaluate()

        alert = Alert.objects.get(monitor=self.monitor)
        assert alert.end_time is None
        assert alert.updates.count() == 1

    def test_alert_records_do_not_send_notifications(self):
        Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='moderate',
        )
        self.fill_hour(40)
        with self.settings(SEND_SMS_ALERTS=True), self.captureOnCommitCallbacks(execute=True):
            AlertEvaluator(self.monitor).evaluate()
        assert Notification.objects.count() == 0

    def test_alert_and_alertupdate_use_integer_pk_and_sqid(self):
        self.fill_hour(40)
        AlertEvaluator(self.monitor).evaluate()
        alert = Alert.objects.get(monitor=self.monitor)
        assert isinstance(alert.pk, int)
        assert alert.sqid

        update = alert.updates.first()
        assert isinstance(update.pk, int)
        assert update.sqid


class HourlyAndMultiPollutantTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.monitor = AirNow.objects.create(
            name='Test AirNow Station',
            position=Point(-119.8, 36.7),
            county='Fresno',
            location='outside',
        )
        self.monitor.is_active = True
        self.pm25_lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]
        self.o3_lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[O3])[0]

    def test_hourly_monitor_uses_latest_reading(self):
        O3.objects.create(
            monitor=self.monitor,
            value=125,  # UNHEALTHY_SENSITIVE
            timestamp=timezone.now() - timedelta(minutes=50),
            **self.o3_lookup
        )
        assert AlertEvaluator(self.monitor).get_levels()[O3] == AQLevel.scale.UNHEALTHY_SENSITIVE

    def test_hourly_monitor_ignores_stale_reading(self):
        O3.objects.create(
            monitor=self.monitor,
            value=125,
            timestamp=timezone.now() - timedelta(hours=5),
            **self.o3_lookup
        )
        assert AlertEvaluator(self.monitor).get_levels()[O3] is None

    def test_two_pollutants_produce_independent_alerts(self):
        PM25.objects.create(monitor=self.monitor, value=60, timestamp=timezone.now(), **self.pm25_lookup)
        O3.objects.create(monitor=self.monitor, value=125, timestamp=timezone.now(), **self.o3_lookup)

        levels = AlertEvaluator(self.monitor).evaluate()
        assert levels[PM25] == AQLevel.scale.UNHEALTHY
        assert levels[O3] == AQLevel.scale.UNHEALTHY_SENSITIVE

        pm25_alert = Alert.objects.get(monitor=self.monitor, entry_type=PM25.entry_type)
        o3_alert = Alert.objects.get(monitor=self.monitor, entry_type=O3.entry_type)
        assert pm25_alert.pk != o3_alert.pk
        assert pm25_alert.updates.count() == 1
        assert o3_alert.updates.count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/alerts/tests.py`
Expected: FAIL. `AttributeError: type object 'AlertEvaluator' has no attribute 'split_config'`
(and similar) in the two new classes.

- [ ] **Step 3: Rewrite `camp/apps/alerts/evaluator.py`**

Replace the whole file with:

```python
import math

import pandas as pd

from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel


class AlertEvaluator:
    # Every level comes from the trailing hour (e.g. 3:10-4:10 at 4:10).
    WINDOW = pd.Timedelta('60m')
    MINIMUM_DURATION = pd.Timedelta('60m')
    # Share of the expected readings that must be in WINDOW before an
    # average counts, so one reading (or a mostly-offline hour) can't
    # decide the level.
    MIN_COVERAGE = 0.5

    def __init__(self, monitor):
        self.monitor = monitor
        self.entry_types = monitor.alertable_entry_types

    @staticmethod
    def split_config(config):
        '''
        Split an ENTRY_CONFIG 'alerts' dict into queryset lookup kwargs and the
        alert stage's expected interval (None = the monitor's EXPECTED_INTERVAL).
        '''
        lookup = {key: value for key, value in config.items() if key != 'expected_interval'}
        return lookup, config.get('expected_interval')

    def get_levels(self):
        '''
        Return {entry_model: Level or None} for every alertable entry type,
        without touching alert records.
        '''
        return {
            entry_model: self.get_level(entry_model, *self.split_config(config))
            for entry_model, config in self.entry_types.items()
        }

    def evaluate(self):
        '''
        Bring this monitor's alert records in line with its trailing-hour
        levels, and return those levels (see get_levels). Alert records are
        bookkeeping only; subscriber texts are decided in notifications.py.
        '''
        levels = self.get_levels()
        for entry_model, level in levels.items():
            with transaction.atomic():
                active_alert = (Alert.objects
                    .select_for_update()
                    .filter(
                        monitor_id=self.monitor.pk,
                        entry_type=entry_model.entry_type,
                        end_time__isnull=True,
                    )
                    .first()
                )
                if active_alert is not None:
                    self.update_check(active_alert, level)
                elif self.monitor.is_active:
                    self.creation_check(entry_model, level)
        return levels

    def get_level(self, entry_model, lookup, interval=None):
        interval = pd.to_timedelta(interval or self.monitor.EXPECTED_INTERVAL)
        if interval >= self.WINDOW:
            # An hourly feed can't be averaged over an hour: use its latest reading.
            return self.get_current_level(entry_model, lookup, interval)
        return self.get_average_level(entry_model, lookup, interval)

    def get_average_level(self, entry_model, lookup, interval):
        now = timezone.now()
        result = (entry_model.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp__gte=now - self.WINDOW,
                timestamp__lte=now,
                **lookup
            )
            .aggregate(avg=Avg('value'), count=Count('value'))
        )

        required = max(1, math.ceil((self.WINDOW / interval) * self.MIN_COVERAGE))
        if result['count'] < required:
            return None
        return entry_model.Levels.get_level(result['avg'])

    def get_current_level(self, entry_model, lookup, interval):
        '''
        Level of the most recent reading, or None if it is older than twice
        the expected interval.
        '''
        now = timezone.now()
        entry = (entry_model.objects
            .filter(monitor_id=self.monitor.pk, timestamp__lte=now, **lookup)
            .order_by('-timestamp')
            .first()
        )
        if not entry or now - entry.timestamp > interval * 2:
            return None
        return entry_model.Levels.get_level(entry.value)

    def creation_check(self, entry_model, level):
        if level is None or level < AQLevel.scale.MODERATE:
            return None

        now = timezone.now()
        alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=entry_model.entry_type,
            start_time=now,
        )
        alert.create_update(level, timestamp=now)
        return alert

    def update_check(self, alert, level):
        if level is None or level == alert.updates.latest().get_level():
            return

        now = timezone.now()
        if level == AQLevel.scale.GOOD:
            if now - alert.start_time < self.MINIMUM_DURATION:
                return
            alert.end_time = now
            alert.save(update_fields=['end_time'])
        alert.create_update(level, timestamp=now)
```

- [ ] **Step 4: Stop `Alert.create_update` from notifying**

In `camp/apps/alerts/models.py`, replace `Alert.create_update`:

```python
    def create_update(self, level, timestamp=None):
        return AlertUpdate.objects.create(
            alert_id=self.pk,
            level=level.key,
            timestamp=timestamp or timezone.now(),
        )
```

(`timezone` is already imported in `models.py`.)

- [ ] **Step 5: Mark AQLite's alert stage as hourly**

In `camp/apps/monitors/aqlite/models.py`, change
`'alerts': {'stage': entry_models.O3.Stage.CALIBRATED},` to:

```python
            # The calibrated stage is an hourly aggregate even though raw
            # readings arrive every 5 minutes.
            'alerts': {
                'stage': entry_models.O3.Stage.CALIBRATED,
                'expected_interval': '1h',
            },
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/alerts camp/apps/monitors/aqlite`
Expected: all pass.

- [ ] **Step 7: Check for other callers of the removed names**

Run: `grep -rn "ESCALATION_WINDOW\|DEESCALATION_WINDOW\|NOTIFICATION_COOLDOWN\|SEVERITY_BYPASS_RANKS\|get_current_level(" camp --include='*.py'`
Expected: matches only inside `camp/apps/alerts/evaluator.py`. Fix any other hit.

- [ ] **Step 8: Leave uncommitted**

Do not commit. Report the changed files.

---

### Task 2: Scheduler evaluates every relevant monitor once, under a lock; one open alert per pollutant

**Files:**
- Modify: `camp/apps/alerts/tasks.py:1-65` (imports, `periodic_alerts`; add `get_alert_monitors`)
- Modify: `camp/apps/alerts/models.py` (`Alert.Meta`)
- Create: `camp/apps/alerts/migrations/0007_alert_one_open_per_entry_type.py` (via makemigrations)
- Test: `camp/apps/alerts/tests.py` (new class `PeriodicAlertsTests`)

**Interfaces:**
- **Consumes:** `AlertEvaluator.evaluate()` (Task 1).
- **Produces:**
  - `tasks.get_alert_monitors() -> Iterator[Monitor subclass instance]`
  - `tasks.periodic_alerts` (`db_periodic_task`)
  - constraint name `one_open_alert_per_monitor_entry_type`

- [ ] **Step 1: Write the failing tests**

Add these imports at the top of `camp/apps/alerts/tests.py`, next to the existing ones:

```python
import pytest

from django.db import IntegrityError, transaction

from camp.apps.alerts.tasks import get_alert_monitors, periodic_alerts
from camp.apps.monitors.models import LatestEntry
```

Append this class:

```python
class PeriodicAlertsTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]

    def create_airnow(self):
        return AirNow.objects.create(
            name='Test AirNow Station',
            position=Point(-119.8, 36.7),
            county='Fresno',
            location='outside',
        )

    def mark_active(self, monitor):
        # get_active() reads LatestEntry, which raw entry creation doesn't touch.
        lookup = AlertEvaluator.split_config(monitor.alertable_entry_types[PM25])[0]
        entry = PM25.objects.create(monitor=monitor, value=5, timestamp=timezone.now(), **lookup)
        LatestEntry.objects.create(
            monitor=monitor,
            entry_type=PM25.entry_type,
            stage=entry.stage,
            processor='',
            entry_id=entry.pk,
            timestamp=entry.timestamp,
        )

    def test_evaluates_active_monitor_without_alert_history(self):
        self.mark_active(self.monitor)
        for i in range(30):
            PM25.objects.create(
                monitor=self.monitor,
                value=40,
                timestamp=timezone.now() - timedelta(minutes=i * 2),
                **self.lookup
            )
        periodic_alerts.call_local()
        assert Alert.objects.filter(monitor=self.monitor, end_time__isnull=True).count() == 1

    def test_skips_inactive_monitor_without_open_alert(self):
        assert self.monitor.pk not in [monitor.pk for monitor in get_alert_monitors()]

    def test_includes_offline_monitor_with_open_alert(self):
        Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now())
        monitors = list(get_alert_monitors())
        assert [monitor.pk for monitor in monitors] == [self.monitor.pk]
        assert isinstance(monitors[0], PurpleAir)

    def test_yields_each_monitor_once(self):
        airnow = self.create_airnow()
        self.mark_active(airnow)
        Alert.objects.create(monitor=airnow, entry_type=PM25.entry_type, start_time=timezone.now())
        Alert.objects.create(monitor=airnow, entry_type=O3.entry_type, start_time=timezone.now())

        pks = [monitor.pk for monitor in get_alert_monitors()]
        assert pks.count(airnow.pk) == 1

    def test_only_one_open_alert_per_monitor_and_entry_type(self):
        Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now())
        with pytest.raises(IntegrityError), transaction.atomic():
            Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now())

    def test_closed_alert_does_not_block_a_new_one(self):
        now = timezone.now()
        Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=now, end_time=now)
        Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=now)
        assert Alert.objects.filter(monitor=self.monitor).count() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/alerts/tests.py`
Expected: ImportError: `cannot import name 'get_alert_monitors'`.

- [ ] **Step 3: Add the partial unique constraint**

In `camp/apps/alerts/models.py`, change `Alert.Meta` to:

```python
    class Meta:
        ordering = ['-start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['monitor', 'entry_type'],
                condition=models.Q(end_time__isnull=True),
                name='one_open_alert_per_monitor_entry_type',
            ),
        ]
```

Then generate the migration. Use the TEST command with
`test pytest <PATHS> ...` replaced by
`test python manage.py makemigrations alerts --name alert_one_open_per_entry_type`.

Expected: it creates `camp/apps/alerts/migrations/0007_alert_one_open_per_entry_type.py`,
containing a single `migrations.AddConstraint` with that name and condition. Open it and
confirm it contains nothing else.

- [ ] **Step 4: Rewrite the scheduler in `camp/apps/alerts/tasks.py`**

Replace the imports block and the `periodic_alerts` function (lines 1–40 today) with the
code below. Leave `send_alert_notification` unchanged in this task.

```python
from random import choice

from django_huey import db_task, db_periodic_task, get_queue
from huey import crontab
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

import twilio.rest

from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification
from camp.apps.monitors.models import Monitor


def get_alert_monitors():
    '''
    Every monitor that needs evaluating, each exactly once: active monitors
    of every type that has alertable entry types, plus any monitor with an
    open alert (so alerts on monitors that went offline can still close).
    '''
    open_alert_ids = set(Alert.objects
        .filter(end_time__isnull=True)
        .values_list('monitor_id', flat=True)
    )
    seen = set()
    for monitor_model in Monitor.get_subclasses():
        if not monitor_model.alertable_entry_types:
            continue

        active_ids = set(monitor_model.objects.get_active().values_list('pk', flat=True))
        for monitor in monitor_model.objects.filter(pk__in=active_ids | open_alert_ids):
            if monitor.pk not in seen:
                seen.add(monitor.pk)
                yield monitor


@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    '''
    Every 10 minutes: bring every relevant monitor's alerts up to date.
    Locked so a slow run can't overlap the next one.
    '''
    with get_queue('primary').lock_task('periodic-alerts'):
        for monitor in get_alert_monitors():
            AlertEvaluator(monitor).evaluate()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/alerts`
Expected: all pass.

Then run: TEST with `test pytest ...` replaced by
`test python manage.py makemigrations alerts --check --dry-run`
Expected: `No changes detected in app 'alerts'`.

- [ ] **Step 6: Leave uncommitted**

Do not commit. Report the changed and created files.

---

### Task 3: Per-subscription escalation rules, plain-text messages, wiring, `www` callback

**Files:**
- Modify: `camp/apps/alerts/models.py` (`Subscription` fields and methods, `Notification` fields)
- Create: `camp/apps/alerts/migrations/0008_subscription_notification_state.py` (via makemigrations)
- Modify: `camp/apps/alerts/notifications.py` (full rewrite below)
- Modify: `camp/apps/alerts/tasks.py` (`periodic_alerts` wiring, `send_alert_notification` callback URL)
- Modify: `camp/apps/alerts/admin.py` (show the new fields)
- Test: `camp/apps/alerts/tests.py`
  - new classes `AlertRuleTests`, `MessageTests`, `NotifySubscribersTests`;
  - one new test in `PeriodicAlertsTests`.

**Interfaces:**
- **Consumes:**
  - `AlertEvaluator.evaluate()` / `get_levels()` (Task 1)
  - `tasks.get_alert_monitors()` and the `PeriodicAlertsTests.mark_active` / `create_airnow`
    helpers (Task 2)
- **Produces:**
  - `Subscription.last_notified_level: str` (blank = re-armed)
  - `Subscription.last_notified_at: datetime | None`
  - `Subscription.below_threshold_since: datetime | None`
  - `Subscription.get_threshold() -> Level`
  - `Subscription.get_last_notified_level() -> Level | None`
  - `Notification.Kind` (`ALERT='alert'`, `REMINDER='reminder'`), `Notification.kind`,
    `Notification.level`
  - `notifications.get_monitor_level(levels) -> tuple[EntryModel | None, Level | None]`
  - `notifications.get_alert_level(subscription, level, now) -> Level | None` (mutates
    the subscription's tracking fields; the caller saves)
  - `notifications.build_message(monitor, entry_model, level, kind) -> str`
  - `notifications.process_subscriptions(monitor, levels, rule, kind) -> list[Notification]`
  - `notifications.notify_subscribers(monitor, levels) -> list[Notification]`
  - constants `MIN_INTERVAL`, `BYPASS_RANKS`, `RESET_AFTER`, `REMINDER_HOUR`

- [ ] **Step 1: Write the failing tests**

Add these imports at the top of `camp/apps/alerts/tests.py`:

```python
from datetime import datetime, timezone as dt_timezone

from camp.apps.alerts import notifications
```

Append these classes:

```python
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=dt_timezone.utc)
MODERATE = AQLevel.scale.MODERATE
USG = AQLevel.scale.UNHEALTHY_SENSITIVE
UNHEALTHY = AQLevel.scale.UNHEALTHY
VERY_UNHEALTHY = AQLevel.scale.VERY_UNHEALTHY

GSM_7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)


class AlertRuleTests(TestCase):
    def subscription(self, **kwargs):
        kwargs.setdefault('level', 'unhealthy_sensitive')
        return Subscription(**kwargs)

    def test_first_reading_at_threshold_texts(self):
        assert notifications.get_alert_level(self.subscription(), USG, NOW) == USG

    def test_subscriber_threshold_is_respected(self):
        assert notifications.get_alert_level(self.subscription(level='unhealthy'), USG, NOW) is None

    def test_below_threshold_never_texts_and_starts_the_dip_clock(self):
        subscription = self.subscription()
        assert notifications.get_alert_level(subscription, MODERATE, NOW) is None
        assert subscription.below_threshold_since == NOW

    def test_same_level_does_not_retext(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=5))
        assert notifications.get_alert_level(subscription, USG, NOW) is None

    def test_lower_level_does_not_text_or_lower_the_bar(self):
        subscription = self.subscription(last_notified_level='unhealthy', last_notified_at=NOW - timedelta(hours=5))
        assert notifications.get_alert_level(subscription, USG, NOW) is None
        assert subscription.last_notified_level == 'unhealthy'

    def test_one_rank_rise_waits_for_two_hours(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(minutes=119))
        assert notifications.get_alert_level(subscription, UNHEALTHY, NOW) is None

    def test_one_rank_rise_after_two_hours_texts(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=2))
        assert notifications.get_alert_level(subscription, UNHEALTHY, NOW) == UNHEALTHY

    def test_two_rank_rise_bypasses_the_limit(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(minutes=10))
        assert notifications.get_alert_level(subscription, VERY_UNHEALTHY, NOW) == VERY_UNHEALTHY

    def test_short_dip_does_not_rearm(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=6))
        notifications.get_alert_level(subscription, MODERATE, NOW - timedelta(minutes=90))
        assert notifications.get_alert_level(subscription, MODERATE, NOW) is None
        assert subscription.last_notified_level == 'unhealthy_sensitive'
        assert notifications.get_alert_level(subscription, USG, NOW + timedelta(minutes=10)) is None

    def test_two_hours_below_threshold_rearms(self):
        subscription = self.subscription(
            last_notified_level='unhealthy_sensitive',
            last_notified_at=NOW - timedelta(hours=6),
            below_threshold_since=NOW - timedelta(hours=2),
        )
        assert notifications.get_alert_level(subscription, MODERATE, NOW) is None
        assert subscription.last_notified_level == ''
        assert notifications.get_alert_level(subscription, USG, NOW + timedelta(minutes=10)) == USG

    def test_back_above_threshold_resets_the_dip_clock(self):
        subscription = self.subscription(
            last_notified_level='unhealthy_sensitive',
            last_notified_at=NOW - timedelta(hours=6),
            below_threshold_since=NOW - timedelta(minutes=90),
        )
        notifications.get_alert_level(subscription, USG, NOW)
        assert subscription.below_threshold_since is None

    def test_monitor_level_is_the_worst_pollutant(self):
        assert notifications.get_monitor_level({PM25: USG, O3: UNHEALTHY}) == (O3, UNHEALTHY)

    def test_monitor_level_ignores_missing_pollutants(self):
        assert notifications.get_monitor_level({PM25: None, O3: MODERATE}) == (O3, MODERATE)

    def test_monitor_level_is_none_when_all_missing(self):
        assert notifications.get_monitor_level({PM25: None}) == (None, None)


class MessageTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.monitor.name = 'X' * 40

    def test_every_message_is_gsm7_and_at_most_two_segments(self):
        for level in AQLevel.scale:
            for kind in Notification.Kind.values:
                message = notifications.build_message(self.monitor, PM25, level, kind)
                assert set(message) <= GSM_7_BASIC, message
                assert len(message) <= 306, message

    def test_alert_message_content(self):
        message = notifications.build_message(self.monitor, PM25, USG, Notification.Kind.ALERT)
        assert message.startswith('SJVAir alert: Air quality is Unhealthy for Sensitive Groups (PM2.5) at ')
        assert message.endswith(f'https://www.sjvair.com/monitor/{self.monitor.pk}')

    def test_reminder_message_content(self):
        message = notifications.build_message(self.monitor, PM25, USG, Notification.Kind.REMINDER)
        assert message.startswith('SJVAir: Air quality is still Unhealthy for Sensitive Groups (PM2.5) at ')


class NotifySubscribersTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')
        self.subscription = Subscription.objects.create(
            user=self.user, monitor=self.monitor, level='unhealthy_sensitive',
        )
        self.alert = Alert.objects.create(
            monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now(),
        )
        self.update = self.alert.create_update(USG)

    def notify(self, level, enabled=True):
        with self.settings(SEND_SMS_ALERTS=enabled), self.captureOnCommitCallbacks(execute=True):
            return notifications.notify_subscribers(self.monitor, {PM25: level})

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_sends_and_records_state(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')

        queued = self.notify(USG)

        assert len(queued) == 1
        notification = Notification.objects.get()
        assert notification.kind == Notification.Kind.ALERT
        assert notification.level == 'unhealthy_sensitive'
        assert notification.alert_update == self.update
        assert notification.status == Notification.Status.SENT
        assert notification.provider_id == 'SM_test_sid'

        kwargs = mock_client_class.return_value.messages.create.call_args.kwargs
        assert kwargs['body'] == notification.message
        assert kwargs['status_callback'].startswith('https://www.sjvair.com/')

        self.subscription.refresh_from_db()
        assert self.subscription.last_notified_level == 'unhealthy_sensitive'
        assert self.subscription.last_notified_at is not None

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_next_tick_at_same_level_does_not_resend(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')
        self.notify(USG)
        self.notify(USG)
        assert Notification.objects.count() == 1

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_below_threshold_records_the_dip_without_sending(self, mock_client_class):
        assert self.notify(MODERATE) == []
        self.subscription.refresh_from_db()
        assert self.subscription.below_threshold_since is not None
        mock_client_class.return_value.messages.create.assert_not_called()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_offline_monitor_changes_nothing(self, mock_client_class):
        assert self.notify(None) == []
        self.subscription.refresh_from_db()
        assert self.subscription.below_threshold_since is None
        assert self.subscription.last_notified_level == ''

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_send_sms_alerts_disabled_skips_entirely(self, mock_client_class):
        assert self.notify(USG, enabled=False) == []
        self.subscription.refresh_from_db()
        assert self.subscription.last_notified_level == ''
        mock_client_class.return_value.messages.create.assert_not_called()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_unverified_phone_subscriber_is_not_notified(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')
        unverified_user = User.objects.create_user(
            email='unverified@sjvair.com',
            password='password',
            full_name='Jane Unverified',
            phone='559-555-1234',
            phone_verified=False,
        )
        Subscription.objects.create(user=unverified_user, monitor=self.monitor, level='unhealthy_sensitive')

        self.notify(USG)

        assert not Notification.objects.filter(user=unverified_user).exists()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_no_open_alert_sends_nothing_and_stays_armed(self, mock_client_class):
        Alert.objects.filter(pk=self.alert.pk).update(end_time=timezone.now())
        assert self.notify(USG) == []
        self.subscription.refresh_from_db()
        assert self.subscription.last_notified_level == ''

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_reopened_alert_does_not_retext_before_rearm(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')
        self.notify(USG)

        Alert.objects.filter(pk=self.alert.pk).update(end_time=timezone.now())
        reopened = Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now())
        reopened.create_update(USG)
        self.notify(USG)

        assert Notification.objects.count() == 1

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_ozone_driven_text_cites_ozone(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')
        airnow = AirNow.objects.create(
            name='Test AirNow Station', position=Point(-119.8, 36.7), county='Fresno', location='outside',
        )
        Subscription.objects.create(user=self.user, monitor=airnow, level='unhealthy_sensitive')
        o3_alert = Alert.objects.create(monitor=airnow, entry_type=O3.entry_type, start_time=timezone.now())
        o3_update = o3_alert.create_update(USG)

        with self.settings(SEND_SMS_ALERTS=True), self.captureOnCommitCallbacks(execute=True):
            notifications.notify_subscribers(airnow, {PM25: MODERATE, O3: USG})

        notification = Notification.objects.get(subscription__monitor=airnow)
        assert notification.alert_update == o3_update
        assert '(Ozone)' in notification.message

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_send_is_deferred_until_transaction_commits(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')

        # No captureOnCommitCallbacks: the send must wait for commit.
        with self.settings(SEND_SMS_ALERTS=True):
            notifications.notify_subscribers(self.monitor, {PM25: USG})

        notification = Notification.objects.get()
        assert notification.status == Notification.Status.QUEUED
        mock_client_class.return_value.messages.create.assert_not_called()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_twilio_failure_is_caught_and_logged(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = TwilioRestException(
            status=400, uri='https://api.twilio.com/fake', msg='Invalid phone number', code=21211,
        )
        self.notify(USG)

        notification = Notification.objects.get()
        assert notification.status == Notification.Status.FAILED
        assert 'Invalid phone number' in notification.error
```

Add this method to `PeriodicAlertsTests` (from Task 2):

```python
    @patch('camp.apps.alerts.tasks.notifications.notify_subscribers')
    def test_notifies_only_subscribed_monitors(self, mock_notify):
        Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='unhealthy_sensitive',
        )
        airnow = self.create_airnow()
        self.mark_active(self.monitor)
        self.mark_active(airnow)

        periodic_alerts.call_local()

        assert [call.args[0].pk for call in mock_notify.call_args_list] == [self.monitor.pk]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/alerts/tests.py`
Expected: FAIL. Errors include `AttributeError: module 'camp.apps.alerts.notifications' has no attribute 'get_alert_level'`
and unknown fields `last_notified_level` / `Notification.Kind`.

- [ ] **Step 3: Add the model fields**

In `camp/apps/alerts/models.py`:

1. Add these fields to `Subscription`, after `level`:

```python
    # Notification state (see notifications.get_alert_level). A blank
    # last_notified_level means the subscription is re-armed.
    last_notified_level = models.CharField(_('Last notified level'), max_length=25, blank=True)
    last_notified_at = models.DateTimeField(_('Last notified at'), null=True, blank=True)
    below_threshold_since = models.DateTimeField(_('Below threshold since'), null=True, blank=True)
```

2. Add these methods to `Subscription`, after `clean`:

```python
    def get_threshold(self):
        return AQLevel.scale[self.level.upper()]

    def get_last_notified_level(self):
        if self.last_notified_level:
            return AQLevel.scale[self.last_notified_level.upper()]
```

3. In `Notification`, add a `Kind` class after `Status`, and two fields after `user`:

```python
    class Kind(models.TextChoices):
        ALERT = 'alert', _('Alert')
        REMINDER = 'reminder', _('Reminder')
```

```python
    kind = models.CharField(_('Kind'), max_length=10, choices=Kind.choices, default=Kind.ALERT)
    level = models.CharField(_('Level'), max_length=25, blank=True)
```

Then generate the migration. Use the TEST command with `test pytest <PATHS> ...` replaced
by `test python manage.py makemigrations alerts --name subscription_notification_state`.
Expected: `0008_subscription_notification_state.py`, containing five `AddField`
operations (three on subscription, two on notification) and nothing else.

- [ ] **Step 4: Rewrite `camp/apps/alerts/notifications.py`**

Replace the whole file with:

```python
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from camp.apps.alerts.models import Alert, Notification, Subscription

logger = logging.getLogger(__name__)

# At most one text per subscription per MIN_INTERVAL, unless the level
# jumps BYPASS_RANKS or more above the last one texted.
MIN_INTERVAL = timedelta(hours=2)
BYPASS_RANKS = 2
# A subscription re-arms (can be texted again at a level it already got)
# once the monitor has stayed below its threshold this long.
RESET_AFTER = timedelta(hours=2)
# Local (Pacific) hour for the daily "still bad" reminder.
REMINDER_HOUR = 10


def get_recipients(monitor):
    return (Subscription.objects
        .filter(monitor_id=monitor.pk, user__phone_verified=True)
        .exclude(user__phone='')
        .select_related('user')
    )


def get_monitor_level(levels):
    '''
    Return (entry_model, level) for the monitor's worst pollutant, or
    (None, None) if no pollutant has a level right now.
    '''
    known = [(entry_model, level) for entry_model, level in levels.items() if level is not None]
    if not known:
        return None, None
    return max(known, key=lambda item: item[1].rank)


def get_alert_level(subscription, level, now):
    '''
    Escalation rule for one subscription. Updates the subscription's
    tracking fields (the caller saves) and returns the level to text, or
    None. Never texts when the air improves.
    '''
    threshold = subscription.get_threshold()
    last = subscription.get_last_notified_level()

    if level < threshold:
        if subscription.below_threshold_since is None:
            subscription.below_threshold_since = now
        elif now - subscription.below_threshold_since >= RESET_AFTER:
            subscription.last_notified_level = ''
        return None

    subscription.below_threshold_since = None
    if last is not None and level <= last:
        return None

    if subscription.last_notified_at and now - subscription.last_notified_at < MIN_INTERVAL:
        floor = last.rank if last is not None else threshold.rank - 1
        if level.rank - floor < BYPASS_RANKS:
            return None

    return level


def build_message(monitor, entry_model, level, kind):
    # Plain GSM-7 text: one emoji would force UCS-2 and double the billed segments.
    params = {'level': level.label, 'pollutant': entry_model.label, 'name': monitor.name}
    if kind == Notification.Kind.REMINDER:
        first_line = _('SJVAir: Air quality is still {level} ({pollutant}) at {name}.')
    else:
        first_line = _('SJVAir alert: Air quality is {level} ({pollutant}) at {name}.')

    lines = [first_line.format(**params)]
    if level.guidance:
        lines.append(str(level.guidance))
    lines.append(f'https://www.sjvair.com{monitor.get_absolute_url()}')
    return '\n'.join(lines)


def get_driving_update(monitor, entry_model):
    alert = (Alert.objects
        .filter(monitor_id=monitor.pk, entry_type=entry_model.entry_type, end_time__isnull=True)
        .select_related('latest')
        .first()
    )
    return alert.latest if alert else None


def process_subscriptions(monitor, levels, rule, kind):
    '''
    Run `rule(subscription, level, now) -> Level | None` for every recipient
    of this monitor, and queue a text for each level it returns. Rows are
    locked so a concurrent alert run and reminder run can't both text the
    same subscription.
    '''
    if not settings.SEND_SMS_ALERTS:
        return []

    entry_model, level = get_monitor_level(levels)
    if level is None:
        return []

    from camp.apps.alerts import tasks

    now = timezone.now()
    queued = []
    with transaction.atomic():
        for subscription in get_recipients(monitor).select_for_update(of=('self',)):
            send_level = rule(subscription, level, now)
            alert_update = None
            if send_level is not None:
                alert_update = get_driving_update(monitor, entry_model)

            if send_level is not None and alert_update is None:
                logger.warning(
                    'No open %s alert on monitor %s; not texting subscription %s',
                    entry_model.entry_type, monitor.pk, subscription.pk,
                )
            elif send_level is not None:
                notification = Notification.objects.create(
                    alert_update=alert_update,
                    subscription=subscription,
                    user=subscription.user,
                    kind=kind,
                    level=send_level.key,
                    message=build_message(monitor, entry_model, send_level, kind),
                )
                subscription.last_notified_level = send_level.key
                subscription.last_notified_at = now
                # Enqueue only once the row is committed, so the worker can see it.
                transaction.on_commit(
                    lambda pk=notification.pk: tasks.send_alert_notification(pk)
                )
                queued.append(notification)

            subscription.save(update_fields=[
                'last_notified_level', 'last_notified_at', 'below_threshold_since',
            ])
    return queued


def notify_subscribers(monitor, levels):
    return process_subscriptions(monitor, levels, get_alert_level, Notification.Kind.ALERT)
```

- [ ] **Step 5: Wire notifications into the scheduler and fix the callback domain**

In `camp/apps/alerts/tasks.py`:

1. Add `Subscription` to the models import and import `notifications`:

```python
from camp.apps.alerts import notifications
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification, Subscription
from camp.apps.monitors.models import Monitor
```

2. Replace the body of `periodic_alerts`:

```python
@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    '''
    Every 10 minutes: bring every relevant monitor's alerts up to date, then
    apply the subscriber texting rules to monitors anyone subscribes to.
    Locked so a slow run can't overlap the next one.
    '''
    with get_queue('primary').lock_task('periodic-alerts'):
        subscribed_ids = set(Subscription.objects.values_list('monitor_id', flat=True))
        for monitor in get_alert_monitors():
            levels = AlertEvaluator(monitor).evaluate()
            if monitor.pk in subscribed_ids:
                notifications.notify_subscribers(monitor, levels)
```

3. In `send_alert_notification`, replace the comment and the `status_callback` argument:

```python
        # Hardcoded production host, not settings/Site-derived: this URL
        # must exactly match what Twilio signs, and Twilio's status
        # callback always hits production regardless of which environment
        # queued the notification. Must be www: the apex sjvair.com is a
        # Squarespace 301 that never reaches Django.
        message = twilio_client.messages.create(
            to=str(notification.user.phone),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=notification.message,
            status_callback=f'https://www.sjvair.com{reverse("twilio-status-callback")}',
        )
```

- [ ] **Step 6: Show the new fields in admin**

In `camp/apps/alerts/admin.py`:
- `SubscriptionAdmin.list_display` becomes
  `['user', 'monitor', 'level', 'last_notified_level', 'last_notified_at']`.
- `NotificationAdmin.list_display` becomes
  `['user', 'kind', 'level', 'status', 'created', 'sent_at']`.
- `NotificationAdmin.list_filter` becomes `['status', 'kind']`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/alerts camp/api/v1/accounts camp/api/v2/accounts`
Expected: all pass.

Then run: TEST with `test pytest ...` replaced by
`test python manage.py makemigrations alerts --check --dry-run`
Expected: `No changes detected in app 'alerts'`.

- [ ] **Step 8: Leave uncommitted**

Do not commit. Report the changed and created files.

---

### Task 4: Daily 10 AM Pacific reminder

**Files:**
- Modify: `camp/apps/alerts/notifications.py` (add `get_reminder_level`, `send_reminders`)
- Modify: `camp/apps/alerts/tasks.py` (add `daily_reminders`)
- Test: `camp/apps/alerts/tests.py` (new classes `ReminderRuleTests`, `SendRemindersTests`, `DailyRemindersTaskTests`)

**Interfaces:**
- **Consumes:**
  - `notifications.process_subscriptions`, `REMINDER_HOUR` (Task 3)
  - `Subscription` tracking fields and `Notification.Kind.REMINDER` (Task 3)
  - `AlertEvaluator.get_levels()` (Task 1)
- **Produces:**
  - `notifications.get_reminder_level(subscription, level, now) -> Level | None`
  - `notifications.send_reminders(monitor, levels) -> list[Notification]`
  - `tasks.daily_reminders` (`db_periodic_task`)

- [ ] **Step 1: Write the failing tests**

Add these imports at the top of `camp/apps/alerts/tests.py`:

```python
from zoneinfo import ZoneInfo

from camp.apps.alerts.tasks import daily_reminders
```

Append:

```python
PACIFIC = ZoneInfo('America/Los_Angeles')


class ReminderRuleTests(TestCase):
    NOW = datetime(2026, 7, 16, 10, 0, tzinfo=PACIFIC)

    def subscription(self, **kwargs):
        kwargs.setdefault('level', 'unhealthy_sensitive')
        kwargs.setdefault('last_notified_level', 'unhealthy')
        kwargs.setdefault('last_notified_at', datetime(2026, 7, 15, 21, 0, tzinfo=PACIFIC))
        return Subscription(**kwargs)

    def test_reminds_when_texted_yesterday_and_still_above_threshold(self):
        assert notifications.get_reminder_level(self.subscription(), UNHEALTHY, self.NOW) == UNHEALTHY

    def test_reports_current_level_even_if_lower_than_last_text(self):
        assert notifications.get_reminder_level(self.subscription(), USG, self.NOW) == USG

    def test_no_reminder_when_already_texted_today(self):
        subscription = self.subscription(last_notified_at=datetime(2026, 7, 16, 0, 30, tzinfo=PACIFIC))
        assert notifications.get_reminder_level(subscription, UNHEALTHY, self.NOW) is None

    def test_no_reminder_after_rearm(self):
        subscription = self.subscription(last_notified_level='')
        assert notifications.get_reminder_level(subscription, UNHEALTHY, self.NOW) is None

    def test_no_reminder_below_threshold(self):
        assert notifications.get_reminder_level(self.subscription(), MODERATE, self.NOW) is None


class SendRemindersTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.subscription = Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='unhealthy_sensitive',
            last_notified_level='unhealthy',
            last_notified_at=timezone.now() - timedelta(days=1),
        )
        alert = Alert.objects.create(monitor=self.monitor, entry_type=PM25.entry_type, start_time=timezone.now())
        alert.create_update(USG)

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_sends_reminder_and_updates_state(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')

        with self.settings(SEND_SMS_ALERTS=True), self.captureOnCommitCallbacks(execute=True):
            queued = notifications.send_reminders(self.monitor, {PM25: USG})

        assert len(queued) == 1
        notification = Notification.objects.get()
        assert notification.kind == Notification.Kind.REMINDER
        assert notification.level == 'unhealthy_sensitive'
        assert notification.message.startswith('SJVAir: Air quality is still Unhealthy for Sensitive Groups')

        self.subscription.refresh_from_db()
        assert self.subscription.last_notified_level == 'unhealthy_sensitive'
        assert timezone.now() - self.subscription.last_notified_at < timedelta(minutes=1)


class DailyRemindersTaskTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.subscription = Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='unhealthy_sensitive',
            last_notified_level='unhealthy_sensitive',
        )

    def run_at(self, when):
        with patch('django.utils.timezone.now', return_value=when), \
                patch('camp.apps.alerts.tasks.notifications.send_reminders') as mock_send:
            daily_reminders.call_local()
        return [call.args[0].pk for call in mock_send.call_args_list]

    def test_runs_at_10am_pdt(self):
        assert self.run_at(datetime(2026, 7, 16, 17, 0, tzinfo=dt_timezone.utc)) == [self.monitor.pk]

    def test_skips_the_other_utc_slot_in_summer(self):
        assert self.run_at(datetime(2026, 7, 16, 18, 0, tzinfo=dt_timezone.utc)) == []

    def test_runs_at_10am_pst(self):
        assert self.run_at(datetime(2026, 1, 16, 18, 0, tzinfo=dt_timezone.utc)) == [self.monitor.pk]

    def test_skips_the_other_utc_slot_in_winter(self):
        assert self.run_at(datetime(2026, 1, 16, 17, 0, tzinfo=dt_timezone.utc)) == []

    def test_skips_monitors_with_only_rearmed_subscriptions(self):
        self.subscription.last_notified_level = ''
        self.subscription.save()
        assert self.run_at(datetime(2026, 7, 16, 17, 0, tzinfo=dt_timezone.utc)) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: TEST with `<PATHS>` = `camp/apps/alerts/tests.py`
Expected: ImportError, `cannot import name 'daily_reminders'`.

- [ ] **Step 3: Add the reminder rule to `camp/apps/alerts/notifications.py`**

Add `from camp.utils.datetime import localtime` to the imports. Then add these two
functions, after `get_alert_level` and at the end of the file respectively:

```python
def get_reminder_level(subscription, level, now):
    '''
    Daily "still bad" rule: only for a subscription that hasn't re-armed,
    is still at or above its threshold, and hasn't been texted about this
    monitor yet today (Pacific). Returns the current level, which may be
    lower than the last one texted.
    '''
    if not subscription.last_notified_level or level < subscription.get_threshold():
        return None

    start_of_day = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if subscription.last_notified_at and subscription.last_notified_at >= start_of_day:
        return None
    return level
```

```python
def send_reminders(monitor, levels):
    return process_subscriptions(monitor, levels, get_reminder_level, Notification.Kind.REMINDER)
```

(`process_subscriptions` never calls a rule with `level=None`, so `get_reminder_level`
doesn't need to handle it.)

- [ ] **Step 4: Add the `daily_reminders` task to `camp/apps/alerts/tasks.py`**

Add `from camp.utils.datetime import localtime` to the imports. Then add this task after
`periodic_alerts`:

```python
@db_periodic_task(crontab(minute='0', hour='17,18'), priority=100)
def daily_reminders():
    '''
    10 AM Pacific "still bad" reminders for multi-day events. Huey crontabs
    run in UTC, so this fires at both 17:00 and 18:00 UTC and only
    proceeds in the run that is 10 AM locally (PDT vs PST).
    '''
    if localtime().hour != notifications.REMINDER_HOUR:
        return

    with get_queue('primary').lock_task('daily-alert-reminders'):
        monitor_ids = (Subscription.objects
            .exclude(last_notified_level='')
            .values_list('monitor_id', flat=True)
            .distinct()
        )
        for monitor in Monitor.objects.filter(pk__in=list(monitor_ids)):
            levels = AlertEvaluator(monitor).get_levels()
            notifications.send_reminders(monitor, levels)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: TEST with `<PATHS>` = `camp/apps/alerts`
Expected: all pass.

- [ ] **Step 6: Leave uncommitted**

Do not commit. Report the changed files.

---

### Task 5: Scenario acceptance tests, docs, full suite

**Files:**
- Create: `camp/apps/alerts/test_scenarios.py`
- Modify: `docs/superpowers/specs/2026-07-09-notifications-redesign-design.md` (supersession note)

**Interfaces:**
- **Consumes:**
  - `AlertEvaluator.evaluate()` and `split_config` (Task 1)
  - `notifications.notify_subscribers` and `BYPASS_RANKS` (Task 3)
  - `tasks.daily_reminders` (Task 4)
- **Produces:** nothing new.

- [ ] **Step 1: Write the scenario tests**

Create `camp/apps/alerts/test_scenarios.py`:

```python
import math
import random
from collections import Counter
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from camp.apps.accounts.models import User
from camp.apps.alerts import notifications, tasks
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Notification, Subscription
from camp.apps.entries.levels import AQLevel
from camp.apps.entries.models import PM25
from camp.apps.monitors.purpleair.models import PurpleAir

PACIFIC = ZoneInfo('America/Los_Angeles')
START = datetime(2026, 7, 15, 0, 0, tzinfo=PACIFIC)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class AlertScenarioTests(TestCase):
    '''
    Replays 10-minute evaluation over synthetic PM2.5 traces (one reading
    every 2 minutes, like PurpleAir) and checks how often a USG subscriber
    gets texted. See
    docs/superpowers/specs/2026-10-06-alert-notification-throttling-design.md.
    '''
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]
        Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='unhealthy_sensitive',
        )

    def run_trace(self, value_at, hours):
        '''
        value_at(minute) -> PM2.5 reading (None for no reading).
        Returns [(sent_at, kind, Level)] in send order.
        '''
        clock = Clock(START)
        sent = []
        with patch('django.utils.timezone.now', clock), \
                patch('camp.apps.alerts.tasks.twilio.rest.Client') as mock_client_class, \
                self.settings(SEND_SMS_ALERTS=True):
            mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_scenario')

            for minute in range(0, hours * 60, 2):
                value = value_at(minute)
                if value is not None:
                    PM25.objects.create(monitor=self.monitor, value=value, timestamp=clock.now, **self.lookup)

                if minute % 10 == 0:
                    seen = set(Notification.objects.values_list('pk', flat=True))
                    monitor = PurpleAir.objects.get(pk=self.monitor.pk)
                    monitor.is_active = True
                    with self.captureOnCommitCallbacks(execute=True):
                        levels = AlertEvaluator(monitor).evaluate()
                        notifications.notify_subscribers(monitor, levels)
                        if minute % 60 == 0:
                            tasks.daily_reminders.call_local()
                    for notification in Notification.objects.exclude(pk__in=seen).order_by('pk'):
                        level = AQLevel.scale[notification.level.upper()]
                        sent.append((clock.now, notification.kind, level))

                clock.now += timedelta(minutes=2)
        return sent

    def assert_spacing(self, sent):
        for (first_at, first_kind, first_level), (next_at, next_kind, next_level) in zip(sent, sent[1:]):
            if next_at - first_at < timedelta(hours=2):
                assert next_level.rank - first_level.rank >= notifications.BYPASS_RANKS, sent

    def assert_daily_volume(self, sent, limit=4):
        for start_at, kind, level in sent:
            window = [item for item in sent if start_at <= item[0] < start_at + timedelta(hours=24)]
            assert len(window) <= limit, sent

    def test_hovering_around_usg(self):
        rng = random.Random(1)
        sent = self.run_trace(lambda m: 35.5 + 4 * math.sin(2 * math.pi * m / 40) + rng.uniform(-1, 1), hours=24)
        assert sent
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_slow_swings_around_usg(self):
        rng = random.Random(2)
        sent = self.run_trace(lambda m: 35.5 + 6 * math.sin(2 * math.pi * m / 180) + rng.uniform(-2, 2), hours=24)
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_noisy_around_unhealthy(self):
        rng = random.Random(4)
        sent = self.run_trace(lambda m: 55.5 + rng.uniform(-25, 25), hours=24)
        assert sent
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_smoke_plumes(self):
        sent = self.run_trace(lambda m: 60 if (m // 90) % 2 == 0 else 5, hours=24)
        assert sent
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_one_bad_reading_per_hour_never_texts(self):
        sent = self.run_trace(lambda m: 400 if m % 60 == 0 else 6, hours=24)
        assert sent == []

    def test_multi_day_smoke_sends_one_alert_and_daily_reminders(self):
        sent = self.run_trace(lambda m: 80, hours=72)
        alerts = [item for item in sent if item[1] == Notification.Kind.ALERT]
        reminders = [item for item in sent if item[1] == Notification.Kind.REMINDER]

        assert len(alerts) == 1
        assert [at.astimezone(PACIFIC).strftime('%m-%d %H:%M') for at, kind, level in reminders] == [
            '07-16 10:00', '07-17 10:00',
        ]
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_daily_afternoon_peaks_rearm_each_day(self):
        # 1-5 PM at Unhealthy, clean otherwise, for four days.
        sent = self.run_trace(lambda m: 70 if 13 <= (m // 60) % 24 < 17 else 5, hours=96)
        per_day = Counter(at.astimezone(PACIFIC).date() for at, kind, level in sent)

        assert len(per_day) == 4
        assert all(1 <= count <= 2 for count in per_day.values())
        assert not [item for item in sent if item[1] == Notification.Kind.REMINDER]
        self.assert_spacing(sent)
```

- [ ] **Step 2: Run the scenarios**

Run: TEST with `<PATHS>` = `camp/apps/alerts/test_scenarios.py`
Expected: all 7 pass.

If one fails, don't loosen the assertion. Report the scenario name, the `sent` list from
the assertion message, and which spec rule it violates. A failure here means the rules
in Task 3/4 don't match the spec.

- [ ] **Step 3: Mark the old evaluator spec section as superseded**

In `docs/superpowers/specs/2026-07-09-notifications-redesign-design.md`, insert this
line directly under the `## 3. Evaluator anti-flapping logic` heading:

```markdown
> **Superseded 2026-10-06** by `2026-10-06-alert-notification-throttling-design.md`: one trailing-hour window, no per-alert cooldown, and per-subscription texting rules in `notifications.py`.
```

- [ ] **Step 4: Run the full suite**

Run: TEST with `<PATHS>` = `camp -n 4 --dist loadscope`
Expected: all pass (≈1,370 tests).

If something fails outside `camp/apps/alerts`, re-run that file alone before treating it
as real. Other worktrees share the DB container, but the private `sjvair_alerts`
DATABASE_URL should isolate it.

- [ ] **Step 5: Leave uncommitted**

Do not commit. Report the full list of changed and created files across the branch
(`git status --short`).
