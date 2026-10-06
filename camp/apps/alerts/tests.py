from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

from camp.apps.accounts.models import User
from camp.apps.alerts import notifications
from camp.apps.alerts.models import Alert, AlertUpdate, Notification, Subscription
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.tasks import daily_reminders, get_alert_monitors, periodic_alerts
from camp.apps.entries.models import O3, PM25
from camp.apps.entries.levels import AQLevel, LevelSet
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.purpleair.models import PurpleAir


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

    def test_delivered_callback_backfills_missing_sent_at(self):
        # setUp creates the notification with sent_at unset, simulating a
        # callback that beat our own SENT write.
        assert self.notification.sent_at is None

        response = self.post_with_signature({
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'delivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.DELIVERED
        assert self.notification.sent_at is not None

    def test_delivered_callback_does_not_overwrite_existing_sent_at(self):
        original_sent_at = timezone.now() - timedelta(minutes=5)
        self.notification.sent_at = original_sent_at
        self.notification.save(update_fields=['sent_at'])

        response = self.post_with_signature({
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'delivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.sent_at == original_sent_at

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

    def test_stale_callback_does_not_revert_terminal_status(self):
        self.notification.status = Notification.Status.DELIVERED
        self.notification.save(update_fields=['status'])

        response = self.post_with_signature({
            'MessageSid': 'SM_test_sid',
            'MessageStatus': 'undelivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.DELIVERED

    def test_empty_sid_does_not_mass_update_notifications(self):
        self.notification.status = Notification.Status.QUEUED
        self.notification.provider_id = ''
        self.notification.save(update_fields=['status', 'provider_id'])

        response = self.post_with_signature({
            'MessageSid': '',
            'MessageStatus': 'delivered',
        })
        assert response.status_code == 200
        self.notification.refresh_from_db()
        assert self.notification.status == Notification.Status.QUEUED


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


class TaskLockTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        cache.delete('alerts:periodic-alerts-lock')
        cache.delete('alerts:daily-reminders-lock')
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]
        entry = PM25.objects.create(monitor=self.monitor, value=5, timestamp=timezone.now(), **lookup)
        LatestEntry.objects.create(
            monitor=self.monitor,
            entry_type=PM25.entry_type,
            stage=entry.stage,
            processor='',
            entry_id=entry.pk,
            timestamp=entry.timestamp,
        )

    def tearDown(self):
        cache.delete('alerts:periodic-alerts-lock')
        cache.delete('alerts:daily-reminders-lock')

    @patch.object(AlertEvaluator, 'evaluate', return_value={})
    def test_held_lock_skips_run_without_raising(self, mock_evaluate):
        cache.set('alerts:periodic-alerts-lock', 'someone-else', 60)
        periodic_alerts.call_local()
        assert not mock_evaluate.called
        assert cache.get('alerts:periodic-alerts-lock') == 'someone-else'

    @patch.object(AlertEvaluator, 'evaluate', return_value={})
    def test_runs_once_lock_is_gone(self, mock_evaluate):
        cache.set('alerts:periodic-alerts-lock', 'someone-else', 60)
        cache.delete('alerts:periodic-alerts-lock')
        periodic_alerts.call_local()
        assert mock_evaluate.call_count == 1

    @patch.object(AlertEvaluator, 'evaluate', return_value={})
    def test_lock_released_after_run(self, mock_evaluate):
        periodic_alerts.call_local()
        assert cache.get('alerts:periodic-alerts-lock') is None

    @patch.object(AlertEvaluator, 'evaluate', side_effect=KeyboardInterrupt)
    def test_lock_released_when_run_aborts(self, mock_evaluate):
        with pytest.raises(KeyboardInterrupt):
            periodic_alerts.call_local()
        assert cache.get('alerts:periodic-alerts-lock') is None

    def test_expired_run_does_not_release_successors_lock(self):
        from camp.apps.alerts.tasks import expiring_lock
        with expiring_lock('alerts:test-lock', 60) as acquired:
            assert acquired
            cache.set('alerts:test-lock', 'successor', 60)
        assert cache.get('alerts:test-lock') == 'successor'
        cache.delete('alerts:test-lock')

    @patch('camp.apps.alerts.tasks.notifications.send_reminders')
    def test_daily_reminders_skips_when_locked(self, mock_send):
        Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'),
            monitor=self.monitor,
            level='unhealthy_sensitive',
            last_notified_level='unhealthy_sensitive',
        )
        cache.set('alerts:daily-reminders-lock', 'someone-else', 60)
        with patch('django.utils.timezone.now', return_value=datetime(2026, 7, 16, 17, 0, tzinfo=dt_timezone.utc)):
            daily_reminders.call_local()
        assert not mock_send.called

    @patch('camp.apps.alerts.tasks.notifications.send_reminders')
    def test_daily_reminders_releases_lock(self, mock_send):
        with patch('django.utils.timezone.now', return_value=datetime(2026, 7, 16, 17, 0, tzinfo=dt_timezone.utc)):
            daily_reminders.call_local()
        assert cache.get('alerts:daily-reminders-lock') is None


class TaskIsolationTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        cache.delete('alerts:periodic-alerts-lock')
        cache.delete('alerts:daily-reminders-lock')
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.airnow = AirNow.objects.create(
            name='Test AirNow Station',
            position=Point(-119.8, 36.7),
            county='Fresno',
            location='outside',
        )
        for monitor in (self.monitor, self.airnow):
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

    def tearDown(self):
        cache.delete('alerts:periodic-alerts-lock')
        cache.delete('alerts:daily-reminders-lock')

    def test_periodic_alerts_continues_after_a_monitor_fails(self):
        evaluated = []

        def fake_evaluate(evaluator):
            evaluated.append(evaluator.monitor.pk)
            if len(evaluated) == 1:
                raise RuntimeError('boom')
            return {}

        with patch.object(AlertEvaluator, 'evaluate', fake_evaluate):
            periodic_alerts.call_local()

        assert sorted(evaluated) == sorted([self.monitor.pk, self.airnow.pk])

    def test_daily_reminders_continues_after_a_monitor_fails(self):
        user = User.objects.get(email='user@sjvair.com')
        for monitor in (self.monitor, self.airnow):
            Subscription.objects.create(
                user=user, monitor=monitor, level='unhealthy_sensitive',
                last_notified_level='unhealthy_sensitive',
            )
        calls = []

        def fake_send(monitor, levels):
            calls.append(monitor.pk)
            if len(calls) == 1:
                raise RuntimeError('boom')

        with patch('django.utils.timezone.now', return_value=datetime(2026, 7, 16, 17, 0, tzinfo=dt_timezone.utc)), \
                patch.object(AlertEvaluator, 'get_levels', return_value={}), \
                patch('camp.apps.alerts.tasks.notifications.send_reminders', fake_send):
            daily_reminders.call_local()

        assert sorted(calls) == sorted([self.monitor.pk, self.airnow.pk])


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

    def test_daily_cap_blocks_a_one_rank_rise(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=3))
        assert notifications.get_alert_level(subscription, UNHEALTHY, NOW, alerts_today=3) is None

    def test_daily_cap_blocks_a_rearmed_first_text(self):
        subscription = self.subscription(last_notified_level='', last_notified_at=NOW - timedelta(hours=3))
        assert notifications.get_alert_level(subscription, USG, NOW, alerts_today=3) is None

    def test_daily_cap_has_no_bypass_without_a_baseline(self):
        for level in (UNHEALTHY, VERY_UNHEALTHY):
            subscription = self.subscription(last_notified_level='', last_notified_at=NOW - timedelta(hours=5))
            assert notifications.get_alert_level(subscription, level, NOW, alerts_today=3) is None

    def test_daily_cap_allows_a_two_rank_rise(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=3))
        assert notifications.get_alert_level(subscription, VERY_UNHEALTHY, NOW, alerts_today=3) == VERY_UNHEALTHY

    def test_under_the_daily_cap_still_texts(self):
        subscription = self.subscription(last_notified_level='unhealthy_sensitive', last_notified_at=NOW - timedelta(hours=3))
        assert notifications.get_alert_level(subscription, UNHEALTHY, NOW, alerts_today=2) == UNHEALTHY

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

    def test_good_threshold_subscription_rearms_after_two_hours(self):
        subscription = self.subscription(
            level='good',
            last_notified_level='moderate',
            last_notified_at=NOW - timedelta(hours=6),
            below_threshold_since=NOW - timedelta(hours=2),
        )
        assert notifications.get_alert_level(subscription, AQLevel.scale.GOOD, NOW) is None
        assert subscription.last_notified_level == ''

    def test_good_threshold_subscription_behaves_as_moderate(self):
        subscription = self.subscription(level='good')
        assert notifications.get_alert_level(subscription, AQLevel.scale.GOOD, NOW) is None
        assert notifications.get_alert_level(subscription, MODERATE, NOW) == MODERATE

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

    def test_accented_name_becomes_plain_ascii(self):
        self.monitor.name = 'Planada \u2013 Se\u00f1ora\u2019s Caf\u00e9 \U0001F32B\ufe0f'
        message = notifications.build_message(self.monitor, PM25, USG, Notification.Kind.ALERT)
        assert "Planada - Senora's Cafe" in message
        assert set(message) <= GSM_7_BASIC, message
        assert len(message) <= 306, message

    def test_long_name_is_truncated(self):
        self.monitor.name = 'Caf\u00e9 [x] ' * 40
        for level in AQLevel.scale:
            for kind in Notification.Kind.values:
                message = notifications.build_message(self.monitor, PM25, level, kind)
                assert set(message) <= GSM_7_BASIC, message
                assert len(message) <= 306, message
        assert '...' in message

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
    def test_unchanged_subscription_is_not_saved(self, mock_client_class):
        mock_client_class.return_value.messages.create.return_value = MagicMock(sid='SM_test_sid')
        self.notify(USG)
        with patch.object(Subscription, 'save') as mock_save:
            self.notify(USG)
        assert not mock_save.called

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_below_threshold_records_the_dip_without_sending(self, mock_client_class):
        assert self.notify(MODERATE) == []
        self.subscription.refresh_from_db()
        assert self.subscription.below_threshold_since is not None
        mock_client_class.return_value.messages.create.assert_not_called()

    @patch('camp.apps.alerts.tasks.twilio.rest.Client')
    def test_good_subscriber_on_good_air_is_silent(self, mock_client_class):
        Subscription.objects.filter(pk=self.subscription.pk).update(level='good')
        with self.assertNoLogs('camp.apps.alerts.notifications', level='WARNING'):
            assert self.notify(AQLevel.scale.GOOD) == []
        assert not Notification.objects.exists()

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


class DailyCapCountTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def test_counts_only_todays_alert_texts(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        subscription = Subscription.objects.create(
            user=User.objects.get(email='user@sjvair.com'), monitor=monitor, level='unhealthy_sensitive',
        )
        alert = Alert.objects.create(monitor=monitor, entry_type=PM25.entry_type, start_time=NOW)
        update = alert.create_update(USG)
        now = datetime(2026, 7, 15, 20, 0, tzinfo=dt_timezone.utc)  # 1 PM Pacific

        def create(kind, created):
            return Notification.objects.create(
                alert_update=update, subscription=subscription, user=subscription.user,
                kind=kind, level='unhealthy_sensitive', message='x', created=created,
            )

        create(Notification.Kind.ALERT, now - timedelta(hours=1))
        create(Notification.Kind.ALERT, now - timedelta(hours=5))
        create(Notification.Kind.REMINDER, now - timedelta(hours=2))
        create(Notification.Kind.ALERT, datetime(2026, 7, 15, 6, 0, tzinfo=dt_timezone.utc))  # 11 PM yesterday

        assert notifications.get_alerts_today(monitor, now) == {subscription.pk: 2}


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
