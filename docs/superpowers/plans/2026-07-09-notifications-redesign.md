# Notifications (Alerts) System Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `alerts` app a persisted notification audit trail (with Twilio delivery-status tracking), decouple SMS sending from the `Alert` model, and harden `AlertEvaluator` against notification flapping.

**Architecture:** A new `Notification` model records every SMS attempt (status, error, Twilio SID). Sending logic moves out of `Alert` into a `notifications.py` module + a dedicated Huey task, with a Twilio status-callback webhook updating delivery status asynchronously. `AlertEvaluator` gets asymmetric escalate (15m) / de-escalate (60m) windows plus a per-alert notification cooldown with a severity bypass. `Alert`/`AlertUpdate` move from the legacy `SmallUUIDField` PK pattern to the project's newer `SqidsField` convention via a destructive migration (historical alert data is not preserved — it's derivable from raw entry values, unlike `Subscription`, which is untouched).

**Tech Stack:** Django, `django_sqids`, `twilio` (already pinned at latest, 9.10.9), `django_huey`, pytest via Django's `TestCase`.

## Global Constraints

- `ESCALATION_WINDOW = 15 minutes` — used for creating a new alert and for escalating an active one
- `DEESCALATION_WINDOW = 60 minutes` — used for de-escalating or closing an active alert (same value as today's `UPDATE_WINDOW`)
- `MINIMUM_DURATION = 60 minutes` — unchanged, alert must be this old before it can close
- `NOTIFICATION_COOLDOWN = 30 minutes` — minimum gap between consecutive notification-triggering updates on the same alert
- `SEVERITY_BYPASS_RANKS = 2` — a level change of 2+ ranks always bypasses the cooldown
- `settings.SEND_SMS_ALERTS` kill switch is preserved as a hard early-return — when off, no `Notification` rows are created at all (not an audited skip)
- No `channel` field, no channel abstraction — SMS via Twilio only
- No changes to `Subscription` (model, data, API, or admin)
- `SqidsField` (`django_sqids`) is a **virtual/computed field** — it requires no database column and needs no migration entry of its own. It wraps an existing integer field (default `real_field_name='id'`), so it can only be added to a model whose primary key is already (or becomes) a plain integer `id` — this is why `Alert` (currently `SmallUUIDField` PK) requires a destructive migration, while `AlertUpdate` (already a default `BigAutoField` PK) does not need its own PK changed, only recreating alongside `Alert` because of the FK between them.
- Twilio's Python package (`twilio==9.10.9` in `requirements/base.txt`) is already the latest release on PyPI — no dependency bump needed as part of this work.

---

### Task 1: `Notification` model

**Files:**
- Modify: `camp/apps/alerts/models.py`
- Create: `camp/apps/alerts/migrations/0005_notification.py`
- Test: `camp/apps/alerts/tests.py`

**Interfaces:**
- Produces: `Notification` model with fields `alert_update` (FK → `AlertUpdate`, `CASCADE`), `subscription` (FK → `Subscription`, nullable, `SET_NULL`), `user` (FK → `accounts.User`, `CASCADE`), `status` (`Notification.Status.QUEUED`/`SENT`/`DELIVERED`/`UNDELIVERED`/`FAILED`, default `QUEUED`), `message` (`TextField`), `provider_id` (`CharField`, blank), `error` (`TextField`, blank), `sent_at` (nullable `DateTimeField`), `sqid` (computed, read-only).

- [ ] **Step 1: Write the failing tests**

Add to `camp/apps/alerts/tests.py`. First, extend the imports at the top of the file:

```python
from camp.apps.accounts.models import User
from camp.apps.alerts.models import Alert, AlertUpdate, Notification, Subscription
```

(The existing `from camp.apps.alerts.models import Alert, AlertUpdate` import should be replaced by the line above — it now also imports `Notification` and `Subscription`.)

Then add a new test class:

```python
class NotificationModelTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')
        self.subscription = Subscription.objects.create(
            user=self.user, monitor=self.monitor, level='unhealthy',
        )
        self.alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=PM25.entry_type,
            start_time=timezone.now(),
        )
        self.alert_update = AlertUpdate.objects.create(
            alert=self.alert, level='unhealthy',
        )

    def test_defaults_to_queued_and_has_sqid(self):
        notification = Notification.objects.create(
            alert_update=self.alert_update,
            subscription=self.subscription,
            user=self.user,
            message='test message',
        )
        assert notification.status == Notification.Status.QUEUED
        assert notification.sqid

    def test_survives_subscription_deletion(self):
        notification = Notification.objects.create(
            alert_update=self.alert_update,
            subscription=self.subscription,
            user=self.user,
            message='test message',
        )
        self.subscription.delete()
        notification.refresh_from_db()
        assert notification.subscription_id is None

    def test_deleted_with_user(self):
        notification = Notification.objects.create(
            alert_update=self.alert_update,
            subscription=self.subscription,
            user=self.user,
            message='test message',
        )
        self.user.delete()
        assert not Notification.objects.filter(pk=notification.pk).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::NotificationModelTests -v`
Expected: FAIL with `ImportError: cannot import name 'Notification' from 'camp.apps.alerts.models'`

- [ ] **Step 3: Add the `Notification` model**

In `camp/apps/alerts/models.py`, add `SqidsField`/`shuffle_alphabet` to the imports (after the existing `django_smalluuid.models` import on line 11):

```python
from django_smalluuid.models import SmallUUIDField, uuid_default
from django_sqids import SqidsField, shuffle_alphabet
from model_utils import Choices
from model_utils.models import TimeStampedModel
```

Then append the new model at the end of the file, after `AlertUpdate`:

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

    status = models.CharField(max_length=11, choices=Status.choices, default=Status.QUEUED)
    message = models.TextField()
    provider_id = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f'Notification for {self.user_id} @ {self.status}'
```

- [ ] **Step 4: Write the migration by hand**

Create `camp/apps/alerts/migrations/0005_notification.py`:

```python
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('alerts', '0004_alert_latest'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('undelivered', 'Undelivered'), ('failed', 'Failed')], default='queued', max_length=11)),
                ('message', models.TextField()),
                ('provider_id', models.CharField(blank=True, max_length=64)),
                ('error', models.TextField(blank=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('alert_update', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='alerts.alertupdate')),
                ('subscription', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notifications', to='alerts.subscription')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created'],
            },
        ),
    ]
```

- [ ] **Step 5: Apply the migration**

Run: `docker compose run --rm web python manage.py migrate alerts`
Expected: `Applying alerts.0005_notification... OK`

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::NotificationModelTests -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add camp/apps/alerts/models.py camp/apps/alerts/migrations/0005_notification.py camp/apps/alerts/tests.py
git commit -m "feat(alerts): add Notification model for delivery audit trail"
```

---

### Task 2: Migrate `Alert`/`AlertUpdate` to sqids (destructive)

**Files:**
- Modify: `camp/apps/alerts/models.py:65-96` (Alert), `camp/apps/alerts/models.py:143-153` (AlertUpdate)
- Create: `camp/apps/alerts/migrations/0006_alert_alertupdate_sqids.py`
- Test: `camp/apps/alerts/tests.py`

**Interfaces:**
- Consumes: `Notification` model from Task 1 (its `alert_update` FK must be dropped and re-added around this migration, since it points at the table being recreated).
- Produces: `Alert.pk` / `AlertUpdate.pk` are now plain integers; both have a `.sqid` string property. No other model or call site changes.

- [ ] **Step 1: Write the failing test**

Add to `AlertEvaluatorTests` in `camp/apps/alerts/tests.py`:

```python
    def test_alert_and_alertupdate_use_integer_pk_and_sqid(self):
        self.create_pm25_entry(40, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)

        assert isinstance(alert.pk, int)
        assert alert.sqid

        update = alert.updates.first()
        assert isinstance(update.pk, int)
        assert update.sqid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::AlertEvaluatorTests::test_alert_and_alertupdate_use_integer_pk_and_sqid -v`
Expected: FAIL — `alert.pk` is currently a `SmallUUIDField` value (not an `int`), and `alert.sqid` / `update.sqid` don't exist yet (`AttributeError`).

- [ ] **Step 3: Update the model definitions**

In `camp/apps/alerts/models.py`, replace the `Alert` class's `id` field:

```python
class Alert(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.Alert'))

    monitor = models.ForeignKey('monitors.Monitor', related_name='alerts', on_delete=models.CASCADE)
    entry_type = EntryTypeField()

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)

    latest = models.OneToOneField(
        'alerts.AlertUpdate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    class Meta:
        ordering = ['-start_time']
```

(This removes the old `id = SmallUUIDField(...)` block entirely — Django adds the default `BigAutoField` `id` automatically.)

And add `sqid` to `AlertUpdate`:

```python
class AlertUpdate(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.AlertUpdate'))

    alert = models.ForeignKey('alerts.Alert', related_name='updates', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now)
    level = models.CharField(max_length=25)

    class Meta:
        get_latest_by = 'timestamp'
        ordering = ['timestamp']
```

- [ ] **Step 4: Write the migration by hand**

This is destructive: it drops and recreates `Alert` and `AlertUpdate`, including breaking and re-adding the FKs that point at them (`Alert.latest` and `Notification.alert_update`), since Postgres won't let you drop a table a live FK constraint still references.

Create `camp/apps/alerts/migrations/0006_alert_alertupdate_sqids.py`:

```python
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import camp.apps.entries.fields
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0017_auto_20210312_1234'),
        ('alerts', '0005_notification'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='alert',
            name='latest',
        ),
        migrations.RemoveField(
            model_name='notification',
            name='alert_update',
        ),
        migrations.DeleteModel(
            name='AlertUpdate',
        ),
        migrations.DeleteModel(
            name='Alert',
        ),
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('entry_type', camp.apps.entries.fields.EntryTypeField(max_length=50)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField(blank=True, null=True)),
                ('monitor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='monitors.monitor')),
            ],
            options={
                'ordering': ['-start_time'],
            },
        ),
        migrations.CreateModel(
            name='AlertUpdate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
                ('level', models.CharField(max_length=25)),
                ('alert', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='updates', to='alerts.alert')),
            ],
            options={
                'ordering': ['timestamp'],
                'get_latest_by': 'timestamp',
            },
        ),
        migrations.AddField(
            model_name='alert',
            name='latest',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='alerts.alertupdate'),
        ),
        migrations.AddField(
            model_name='notification',
            name='alert_update',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='alerts.alertupdate'),
        ),
    ]
```

- [ ] **Step 5: Inspect the SQL before applying**

Run: `docker compose run --rm web python manage.py sqlmigrate alerts 0006`
Expected: Output shows `DROP TABLE`/`CREATE TABLE` statements for `alerts_alertupdate` and `alerts_alert`, and `ALTER TABLE`/`DROP CONSTRAINT`/`ADD CONSTRAINT` statements for the `latest` and `alert_update` foreign keys. No errors.

- [ ] **Step 6: Apply the migration**

Run: `docker compose run --rm web python manage.py migrate alerts`
Expected: `Applying alerts.0006_alert_alertupdate_sqids... OK`

- [ ] **Step 7: Run the full alerts test suite**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py -v`
Expected: all tests pass, including the new `test_alert_and_alertupdate_use_integer_pk_and_sqid` and every pre-existing `AlertEvaluatorTests` case.

- [ ] **Step 8: Confirm no migration drift remains for `alerts`**

Run: `docker compose run --rm web python manage.py makemigrations alerts --check --dry-run`
Expected: exits cleanly with no output for `alerts` (the project has pre-existing, unrelated pending-migration drift in `ceidars`/`ces`/`entries`/`pesticides` — ignore those, out of scope for this work).

- [ ] **Step 9: Commit**

```bash
git add camp/apps/alerts/models.py camp/apps/alerts/migrations/0006_alert_alertupdate_sqids.py camp/apps/alerts/tests.py
git commit -m "feat(alerts): migrate Alert/AlertUpdate from SmallUUIDField to sqids

Destructive: existing alert history is not preserved. It's derivable
from raw entry values if ever needed, unlike Subscription data which
is untouched."
```

---

### Task 3: `notifications.py` module + wiring

**Files:**
- Create: `camp/apps/alerts/notifications.py`
- Modify: `camp/apps/alerts/tasks.py`
- Modify: `camp/apps/alerts/models.py:106-140` (Alert.create_update / send_notifications / get_average)
- Test: `camp/apps/alerts/tests.py`

**Interfaces:**
- Consumes: `Notification` model (Task 1), `Subscription`, `Alert`, `AlertUpdate` models.
- Produces: `notifications.get_recipients(alert) -> QuerySet[Subscription]`, `notifications.notify_subscribers(alert_update: AlertUpdate) -> None`, `tasks.send_alert_notification(notification_id) -> None` (Huey `db_task`). `Alert.create_update()` now calls `notifications.notify_subscribers(update)`. `Alert.send_notifications` and `Alert.get_average` are removed.

- [ ] **Step 1: Write the failing tests**

Add to the top of `camp/apps/alerts/tests.py`, alongside existing imports:

```python
from unittest.mock import MagicMock, patch

from twilio.base.exceptions import TwilioRestException
```

Add a new test class:

```python
class NotifySubscribersTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')
        self.alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=PM25.entry_type,
            start_time=timezone.now(),
        )

    def create_subscription(self, level):
        return Subscription.objects.create(
            user=self.user, monitor=self.monitor, level=level,
        )

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_successful_send_marks_notification_sent(self, mock_client_class):
        mock_message = MagicMock(sid='SM_test_sid')
        mock_client_class.return_value.messages.create.return_value = mock_message

        self.create_subscription('moderate')
        update = self.alert.create_update(AQLevel.scale.UNHEALTHY)

        notification = Notification.objects.get(alert_update=update)
        assert notification.status == Notification.Status.SENT
        assert notification.provider_id == 'SM_test_sid'
        assert notification.sent_at is not None

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_twilio_failure_is_caught_and_logged(self, mock_client_class):
        mock_client_class.return_value.messages.create.side_effect = TwilioRestException(
            status=400, uri='https://api.twilio.com/fake', msg='Invalid phone number', code=21211,
        )

        self.create_subscription('moderate')
        update = self.alert.create_update(AQLevel.scale.UNHEALTHY)

        notification = Notification.objects.get(alert_update=update)
        assert notification.status == Notification.Status.FAILED
        assert 'Invalid phone number' in notification.error

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_only_subscribers_meeting_threshold_are_notified(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')

        self.create_subscription('hazardous')
        update = self.alert.create_update(AQLevel.scale.UNHEALTHY)

        assert not Notification.objects.filter(alert_update=update).exists()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_send_sms_alerts_disabled_skips_entirely(self, mock_client_class):
        self.create_subscription('moderate')

        with self.settings(SEND_SMS_ALERTS=False):
            update = self.alert.create_update(AQLevel.scale.UNHEALTHY)

        assert not Notification.objects.filter(alert_update=update).exists()
        mock_client_class.return_value.messages.create.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::NotifySubscribersTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'camp.apps.alerts.notifications'` (or similar, since `create_update` still calls the old `send_notifications`).

- [ ] **Step 3: Create `camp/apps/alerts/notifications.py`**

```python
from django.conf import settings
from django.utils.translation import gettext as _

from camp.apps.alerts import tasks
from camp.apps.alerts.models import Notification, Subscription
from camp.apps.entries.levels import AQLevel


def get_recipients(alert):
    return (Subscription.objects
        .filter(monitor_id=alert.monitor_id)
        .select_related('user')
    )


def notify_subscribers(alert_update):
    if not settings.SEND_SMS_ALERTS:
        return

    alert = alert_update.alert
    level = alert_update.get_level()

    icon = '✅' if level == AQLevel.scale.GOOD else '⚠️'
    message = '\n'.join([
        _('{icon} Air Quality Alert for {name} in {county} County').format(
            icon=icon,
            name=alert.monitor.name,
            county=alert.monitor.county,
        ),
        f'{alert.entry_model.label}: {level.label}',
        f'{level.guidance}\n' or '',
        f'🔗 https://sjvair.com{alert.monitor.get_absolute_url()}',
    ])

    for subscription in get_recipients(alert):
        sub_level = AQLevel.scale[subscription.level.upper()]
        if level < sub_level:
            continue

        notification = Notification.objects.create(
            alert_update=alert_update,
            subscription=subscription,
            user=subscription.user,
            message=message,
        )
        tasks.send_alert_notification(notification.pk)
```

- [ ] **Step 4: Add the `send_alert_notification` task**

Modify `camp/apps/alerts/tasks.py`. Update the imports and add the new task:

```python
from random import choice

from django_huey import db_task, db_periodic_task
from huey import crontab
from django.conf import settings
from django.utils import timezone
from django.db.models import Q

import twilio.rest
from twilio.base.exceptions import TwilioRestException

from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification
from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    """
    Every 10 minutes:
    - Update or end any active alerts.
    - Create alerts for active monitors that don’t currently have one.
    """

    # Part 1: Update existing alerts
    active_alerts = (Alert.objects
        .filter(end_time__isnull=True)
        .select_related('monitor')
    )

    for alert in active_alerts:
        AlertEvaluator(alert.monitor).evaluate()

    # Part 2: Check for new alerts for monitors without alerts
    for monitor_model in Monitor.get_subclasses():
        monitors = (monitor_model.objects
            .get_active()
            .exclude(alerts__end_time__isnull=True)
        )

        for monitor in monitors:
            AlertEvaluator(monitor).evaluate()


@db_task(priority=100)
def send_alert_notification(notification_id):
    notification = Notification.objects.select_related('user').get(pk=notification_id)

    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )

    try:
        message = twilio_client.messages.create(
            to=str(notification.user.phone),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=notification.message,
        )
    except TwilioRestException as exc:
        notification.status = Notification.Status.FAILED
        notification.error = str(exc)
        notification.save(update_fields=['status', 'error'])
        return

    notification.status = Notification.Status.SENT
    notification.sent_at = timezone.now()
    notification.provider_id = message.sid
    notification.save(update_fields=['status', 'sent_at', 'provider_id'])
```

(The `status_callback` argument is added in Task 4, once the webhook URL exists.)

- [ ] **Step 5: Wire `Alert.create_update` and remove the old methods**

In `camp/apps/alerts/models.py`, replace the `create_update`, `send_notifications`, and `get_average` methods on `Alert`:

```python
    def create_update(self, level, **kwargs):
        update = AlertUpdate.objects.create(
            alert_id=self.pk,
            level=level.key,
            **kwargs,
        )
        from camp.apps.alerts import notifications
        notifications.notify_subscribers(update)
        return update
```

This replaces the old `create_update` + `get_average` + `send_notifications` block entirely — `get_average` (the dead, `pm25`-hardcoded method with zero callers) and `send_notifications` (moved to `notifications.py`) are both deleted.

Now clean up the now-unused imports at the top of `models.py`:

```python
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from django_sqids import SqidsField, shuffle_alphabet
from model_utils import Choices
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField
```

Removed: `from datetime import timedelta`, `from django.conf import settings`, `from django.core.exceptions import ValidationError` (still needed — keep it, it's used by `AlertUpdate.clean()`), `from django.db.models import Avg`, `from django.utils.translation import gettext as _`, `from camp.apps.entries.levels import AQLevel`.

To be precise, the final import block at the top of `camp/apps/alerts/models.py` should read:

```python
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from django_sqids import SqidsField, shuffle_alphabet
from model_utils import Choices
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py -v`
Expected: all tests pass, including the four new `NotifySubscribersTests` cases and every pre-existing test.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/alerts/notifications.py camp/apps/alerts/tasks.py camp/apps/alerts/models.py camp/apps/alerts/tests.py
git commit -m "feat(alerts): move SMS sending out of Alert into notifications.py

Alert.send_notifications and the dead, pm25-hardcoded Alert.get_average
are removed. Sending now goes through notifications.notify_subscribers
and a dedicated Huey task, logging every attempt to Notification."
```

---

### Task 4: Twilio delivery-status webhook

**Files:**
- Modify: `camp/apps/alerts/views.py`
- Modify: `camp/urls.py`
- Modify: `camp/apps/alerts/tasks.py` (from Task 3, adds `status_callback`)
- Test: `camp/apps/alerts/tests.py`

**Interfaces:**
- Consumes: `Notification` model (Task 1), `send_alert_notification` task (Task 3).
- Produces: URL name `twilio-status-callback`, resolvable via `reverse('twilio-status-callback')` from anywhere in the project (registered at the top level, not namespaced).

- [ ] **Step 1: Write the failing tests**

Add to the top of `camp/apps/alerts/tests.py`:

```python
from django.urls import reverse

from twilio.request_validator import RequestValidator
```

Add a new test class:

```python
class TwilioStatusCallbackTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')
        self.alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=PM25.entry_type,
            start_time=timezone.now(),
        )
        self.alert_update = AlertUpdate.objects.create(alert=self.alert, level='unhealthy')
        self.notification = Notification.objects.create(
            alert_update=self.alert_update,
            user=self.user,
            message='test message',
            status=Notification.Status.SENT,
            provider_id='SM_test_sid',
        )
        self.url = reverse('twilio-status-callback')

    def post_with_signature(self, data):
        full_url = f'http://testserver{self.url}'
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        signature = validator.compute_signature(full_url, data)
        return self.client.post(self.url, data, HTTP_X_TWILIO_SIGNATURE=signature)

    def test_delivered_status_updates_notification(self):
        response = self.post_with_signature({
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'delivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.DELIVERED

    def test_undelivered_status_updates_notification(self):
        response = self.post_with_signature({
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'undelivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.UNDELIVERED

    def test_invalid_signature_is_rejected(self):
        response = self.client.post(self.url, {
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'delivered',
        }, HTTP_X_TWILIO_SIGNATURE='not-a-real-signature')
        assert response.status_code == 403
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.SENT

    def test_unknown_sid_returns_200_without_error(self):
        response = self.post_with_signature({
            'MessageSid': 'SM_does_not_exist',
            'MessageStatus': 'delivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.SENT
```

Add `from django.conf import settings` to the top of `tests.py` if it isn't already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::TwilioStatusCallbackTests -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'twilio-status-callback' not found`

- [ ] **Step 3: Add the `TwilioStatusCallback` view**

In `camp/apps/alerts/views.py`, add to the imports and add the new view:

```python
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from twilio.request_validator import RequestValidator

from camp.apps.alerts.models import Alert, Notification, Subscription
```

(This replaces the existing `from camp.apps.alerts.models import Alert, Subscription` line — it now also imports `Notification`.)

```python
@method_decorator(csrf_exempt, name='dispatch')
class TwilioStatusCallback(View):
    STATUS_MAP = {
        'delivered': Notification.Status.DELIVERED,
        'undelivered': Notification.Status.UNDELIVERED,
        'failed': Notification.Status.FAILED,
    }

    def post(self, request, *args, **kwargs):
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
        url = request.build_absolute_uri()

        if not validator.validate(url, request.POST, signature):
            return HttpResponseForbidden()

        status = self.STATUS_MAP.get(request.POST.get('MessageStatus'))
        if status is None:
            return HttpResponse(status=200)

        Notification.objects.filter(
            provider_id=request.POST.get('MessageSid')
        ).update(status=status)

        return HttpResponse(status=200)
```

- [ ] **Step 4: Wire the URL**

In `camp/urls.py`, add the import:

```python
from camp.apps.alerts.views import TwilioStatusCallback
```

And add to `urlpatterns` (alongside the other top-level, non-namespaced routes):

```python
    path('webhooks/twilio/status/', TwilioStatusCallback.as_view(), name='twilio-status-callback'),
```

- [ ] **Step 5: Add `status_callback` to the send task**

In `camp/apps/alerts/tasks.py`, add `from django.urls import reverse` to the imports, and update the `messages.create()` call inside `send_alert_notification`:

```python
    try:
        message = twilio_client.messages.create(
            to=str(notification.user.phone),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=notification.message,
            status_callback=f'https://sjvair.com{reverse("twilio-status-callback")}',
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py -v`
Expected: all tests pass, including the four new `TwilioStatusCallbackTests` cases. The `NotifySubscribersTests` cases from Task 3 still pass unchanged since they assert on `Notification` state, not the exact Twilio call arguments.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/alerts/views.py camp/urls.py camp/apps/alerts/tasks.py camp/apps/alerts/tests.py
git commit -m "feat(alerts): add Twilio delivery-status webhook

Notification now tracks delivered/undelivered status via Twilio's
status callback, not just whether the send attempt succeeded."
```

---

### Task 5: Evaluator anti-flapping logic

**Files:**
- Modify: `camp/apps/alerts/evaluator.py`
- Test: `camp/apps/alerts/tests.py`

**Interfaces:**
- Consumes: `Alert.create_update()` (Task 3, now routes through `notifications.notify_subscribers`).
- Produces: `AlertEvaluator.ESCALATION_WINDOW`, `AlertEvaluator.DEESCALATION_WINDOW`, `AlertEvaluator.NOTIFICATION_COOLDOWN`, `AlertEvaluator.SEVERITY_BYPASS_RANKS` — replaces `CREATION_WINDOW`/`UPDATE_WINDOW`. `AlertEvaluator.get_current_level()` now returns `None` for entries older than `2x EXPECTED_INTERVAL`.

- [ ] **Step 1: Write the failing tests**

Add to the top of `camp/apps/alerts/tests.py`:

```python
from django.contrib.gis.geos import Point

from camp.apps.entries.models import O3
from camp.apps.monitors.airnow.models import AirNow
```

Modify the existing `test_update_check_adds_update_when_level_changes` test in `AlertEvaluatorTests` — it currently re-triggers `update_check` with zero elapsed time since the alert's creation, which the new cooldown would (correctly) suppress. Push the last update's timestamp back so the test continues to validate escalation under realistic conditions:

```python
    def test_update_check_adds_update_when_level_changes(self):
        self.create_pm25_entry(60, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)

        # Push the last update outside the notification cooldown window
        # so the escalation below isn't suppressed by it.
        last_update = alert.updates.latest()
        last_update.timestamp = timezone.now() - timedelta(minutes=40)
        last_update.save(update_fields=['timestamp'])

        self.create_pm25_entry(220, minutes_ago=3)
        self.create_pm25_entry(220, minutes_ago=2)
        self.create_pm25_entry(220, minutes_ago=1)
        evaluator.update_check(alert, self.entry_model, self.lookup)

        updates = AlertUpdate.objects.filter(alert=alert)
        assert updates.count() == 2
        assert updates.latest().get_level() > updates.earliest().get_level()
```

Add new test methods to `AlertEvaluatorTests`:

```python
    def test_cooldown_suppresses_rapid_reescalation(self):
        self.create_pm25_entry(10, minutes_ago=5)  # MODERATE
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)
        assert alert.updates.latest().get_level() == AQLevel.scale.MODERATE

        # Replace with entries that average into UNHEALTHY_SENSITIVE (a
        # 1-rank jump) with no time elapsed since the last update.
        self.entry_model.objects.all().delete()
        self.create_pm25_entry(40, minutes_ago=1)
        evaluator.update_check(alert, self.entry_model, self.lookup)

        updates = AlertUpdate.objects.filter(alert=alert)
        assert updates.count() == 1

    def test_severity_bypass_skips_cooldown(self):
        self.create_pm25_entry(10, minutes_ago=5)  # MODERATE
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)
        assert alert.updates.latest().get_level() == AQLevel.scale.MODERATE

        # Jump straight to VERY_UNHEALTHY (rank 4, a 3-rank jump) with no
        # time elapsed — severity bypass should fire immediately.
        self.entry_model.objects.all().delete()
        self.create_pm25_entry(200, minutes_ago=1)
        evaluator.update_check(alert, self.entry_model, self.lookup)

        updates = AlertUpdate.objects.filter(alert=alert)
        assert updates.count() == 2
        assert updates.latest().get_level() == AQLevel.scale.VERY_UNHEALTHY

    def test_get_current_level_ignores_stale_entries(self):
        self.create_pm25_entry(80, minutes_ago=200)
        evaluator = AlertEvaluator(self.monitor)
        level = evaluator.get_current_level(self.entry_model, self.lookup)
        assert level is None
```

Add a new test class for hourly-monitor and multi-pollutant behavior:

```python
class MultiPollutantAndHourlyMonitorTests(TestCase):
    fixtures = ['users.yaml']

    def setUp(self):
        self.monitor = AirNow.objects.create(
            name='Test AirNow Station',
            position=Point(-119.8, 36.7),
            county='Fresno',
            location='outside',
        )
        self.pm25_lookup = self.monitor.alertable_entry_types[PM25]
        self.o3_lookup = self.monitor.alertable_entry_types[O3]

    def test_hourly_monitor_ignores_stale_reading(self):
        O3.objects.create(
            monitor=self.monitor,
            value=125,  # UNHEALTHY_SENSITIVE if fresh
            timestamp=timezone.now() - timedelta(hours=5),
            **self.o3_lookup
        )
        evaluator = AlertEvaluator(self.monitor)
        level = evaluator.get_level(O3, self.o3_lookup, window=evaluator.DEESCALATION_WINDOW)
        assert level is None

    def test_two_pollutants_produce_independent_alerts(self):
        PM25.objects.create(
            monitor=self.monitor, value=60, timestamp=timezone.now(), **self.pm25_lookup
        )
        O3.objects.create(
            monitor=self.monitor, value=125, timestamp=timezone.now(), **self.o3_lookup
        )

        evaluator = AlertEvaluator(self.monitor)
        evaluator.evaluate()

        pm25_alert = Alert.objects.get(monitor=self.monitor, entry_type=PM25.entry_type)
        o3_alert = Alert.objects.get(monitor=self.monitor, entry_type=O3.entry_type)
        assert pm25_alert.pk != o3_alert.pk
        assert pm25_alert.updates.count() == 1
        assert o3_alert.updates.count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py::AlertEvaluatorTests camp/apps/alerts/tests.py::MultiPollutantAndHourlyMonitorTests -v`
Expected: FAIL — `AttributeError: 'AlertEvaluator' object has no attribute 'DEESCALATION_WINDOW'`, and the modified `test_update_check_adds_update_when_level_changes` fails because there's no cooldown suppression yet to guard against (it will currently pass by coincidence, but the new cooldown/bypass/staleness tests fail).

- [ ] **Step 3: Rewrite `camp/apps/alerts/evaluator.py`**

```python
import pandas as pd

from django.db.models import Avg, Count
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel


class AlertEvaluator:
    ESCALATION_WINDOW = pd.Timedelta('15m')
    DEESCALATION_WINDOW = pd.Timedelta('60m')
    MINIMUM_DURATION = pd.Timedelta('60m')
    NOTIFICATION_COOLDOWN = pd.Timedelta('30m')
    SEVERITY_BYPASS_RANKS = 2

    def __init__(self, monitor):
        self.monitor = monitor
        self.entry_types = monitor.alertable_entry_types

    def evaluate(self):
        for entry_model, lookup in self.entry_types.items():
            active_alert = Alert.objects.filter(
                monitor_id=self.monitor.pk,
                entry_type=entry_model.entry_type,
                end_time__isnull=True,
            ).first()

            if not self.monitor.is_active and not active_alert:
                # Inactive monitor with no active alerts – skip it.
                continue

            if active_alert:
                # There's an active alert, so check if we need
                # to update or end it.
                self.update_check(active_alert, entry_model, lookup)
            else:
                # No current alert, check to see if we need to
                # create one.
                self.creation_check(entry_model, lookup)

    def get_level(self, entry_model, lookup, window):
        interval_delta = pd.to_timedelta(self.monitor.EXPECTED_INTERVAL)

        if interval_delta >= window:
            return self.get_current_level(entry_model, lookup)
        return self.get_average_level(entry_model, lookup, window)

    def get_average_level(self, entry_model, lookup, window):
        '''
        Calculate the average value over a specified window and return the corresponding Level.

        Args:
            entry_model: The entry model to query (e.g., PM25).
            window: The averaging window (e.g., ESCALATION_WINDOW or DEESCALATION_WINDOW).

        Returns:
            A Level instance corresponding to the averaged value, or None if no data is available.
        '''

        start = timezone.now() - window
        queryset = entry_model.objects.filter(
            monitor_id=self.monitor.pk,
            timestamp__gte=start,
            **lookup
        )

        result = queryset.aggregate(avg=Avg('value'), count=Count('value'))
        if result['count'] == 0:
            return None
        return entry_model.Levels.get_level(result['avg'])

    def get_current_level(self, entry_model, lookup):
        '''
        Return the Level corresponding to the most recent entry, if within a valid time window.

        The window is determined based on the monitor's EXPECTED_INTERVAL. If the most recent entry
        is too old (more than 2x the expected interval), this returns None.

        Args:
            entry_model: The entry model to query (e.g., PM25).

        Returns:
            A Level instance corresponding to the most recent entry value, or None if no recent data is available.
        '''

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

    def creation_check(self, entry_model, lookup):
        level = self.get_level(entry_model, lookup, window=self.ESCALATION_WINDOW)
        if not level or level < AQLevel.scale.MODERATE:
            # Below moderate (good) so no alert needed.
            return

        alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=entry_model.entry_type,
            start_time=timezone.now(),
        )
        alert.create_update(level, timestamp=alert.start_time)
        return alert

    def update_check(self, alert, entry_model, lookup):
        """
        Escalate quickly (15-minute average), de-escalate or close slowly
        (60-minute average). A minimum gap is enforced between consecutive
        notifications on the same alert, unless the level jumps by 2 or
        more ranks.
        """
        fast_level = self.get_level(entry_model, lookup, window=self.ESCALATION_WINDOW)
        slow_level = self.get_level(entry_model, lookup, window=self.DEESCALATION_WINDOW)

        last_update = alert.updates.latest()
        current_level = last_update.get_level()
        now = timezone.now()

        candidate = None
        if fast_level and fast_level > current_level:
            candidate = fast_level
        elif slow_level and slow_level < current_level:
            candidate = slow_level

        if candidate is None:
            return

        if candidate == AQLevel.scale.GOOD:
            # If the new level is GOOD and the alert has lived long enough, we can end the alert.
            if (now - alert.start_time) >= self.MINIMUM_DURATION:
                alert.end_time = now
                alert.save(update_fields=['end_time'])
                alert.create_update(candidate)
            return

        rank_jump = abs(candidate.rank - current_level.rank)
        time_since_last = now - last_update.timestamp
        if time_since_last < self.NOTIFICATION_COOLDOWN and rank_jump < self.SEVERITY_BYPASS_RANKS:
            # Still within the cooldown and not a big enough jump to bypass it.
            return

        alert.create_update(candidate)
```

- [ ] **Step 4: Run the full alerts test suite**

Run: `docker compose run --rm test pytest camp/apps/alerts/tests.py -v`
Expected: all tests pass — every `AlertEvaluatorTests` case (including the modified and new ones), all `NotificationModelTests`, `NotifySubscribersTests`, `TwilioStatusCallbackTests`, and `MultiPollutantAndHourlyMonitorTests` cases.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/alerts/evaluator.py camp/apps/alerts/tests.py
git commit -m "feat(alerts): harden AlertEvaluator against notification flapping

Escalation uses a 15-minute average, de-escalation/closing uses a
60-minute average (unchanged from before). A 30-minute cooldown
between notifications on the same alert prevents spam from a value
bouncing near a threshold, bypassed for jumps of 2+ ranks. Also fixes
a real bug where get_current_level ignored its own documented
staleness check, relevant to hourly-reporting monitors like AirNow."
```

---

## Self-Review

**Spec coverage:**
- Notification audit log + `get_recipients` seam → Task 1, Task 3
- `Alert`/`AlertUpdate` sqids migration → Task 2
- Dead code removal (`get_average`) → Task 3
- `TwilioRestException` actually caught/logged → Task 3
- Twilio delivery-status webhook → Task 4
- Asymmetric escalate/de-escalate windows → Task 5
- Notification cooldown + severity bypass → Task 5
- `get_current_level` staleness fix → Task 5
- Hourly-monitor handling → Task 5 (`test_hourly_monitor_ignores_stale_reading`)
- Multi-pollutant independence (cooldown scoped per-Alert) → Task 5 (`test_two_pollutants_produce_independent_alerts`)
- `SEND_SMS_ALERTS` kill switch preserved → Task 3 (`test_send_sms_alerts_disabled_skips_entirely`)
- `Subscription` untouched → no task modifies it

**Placeholder scan:** No TBD/TODO markers; every step shows complete code, not descriptions of code.

**Type consistency:** `Notification.Status` values (`QUEUED`/`SENT`/`DELIVERED`/`UNDELIVERED`/`FAILED`) match across Task 1 (model), Task 3 (`send_alert_notification`), and Task 4 (`TwilioStatusCallback.STATUS_MAP`). `notifications.notify_subscribers(alert_update)` signature matches its call site in `Alert.create_update` (Task 3). `AlertEvaluator.DEESCALATION_WINDOW`/`ESCALATION_WINDOW` names match between Task 5's rewritten `evaluator.py` and the tests that reference `evaluator.DEESCALATION_WINDOW` directly.
