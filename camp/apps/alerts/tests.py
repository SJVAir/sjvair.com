from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from twilio.base.exceptions import TwilioRestException

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Alert, AlertUpdate, Notification, Subscription
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.entries.models import PM25
from camp.apps.entries.levels import AQLevel, LevelSet
from camp.apps.monitors.purpleair.models import PurpleAir


class AlertEvaluatorTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.entry_model = PM25
        self.lookup = self.monitor.alertable_entry_types[PM25]

    def create_pm25_entry(self, value, minutes_ago=0):
        PM25.objects.create(
            monitor=self.monitor,
            value=value,
            timestamp=timezone.now() - timedelta(minutes=minutes_ago),
            **self.lookup
        )

    def test_creation_check_creates_alert_above_threshold(self):
        self.create_pm25_entry(40, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        evaluator.creation_check(self.entry_model, self.lookup)

        alerts = Alert.objects.filter(monitor=self.monitor)
        assert alerts.count() == 1

        alert = alerts.first()
        assert alert.entry_type == self.entry_model.entry_type
        assert alert.updates.count() == 1
        assert alert.latest_id is not None
        assert alert.latest == alert.updates.first()

    def test_creation_check_skips_below_threshold(self):
        self.create_pm25_entry(5, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        evaluator.creation_check(self.entry_model, self.lookup)

        assert Alert.objects.filter(monitor=self.monitor).count() == 0

    def test_update_check_adds_update_when_level_changes(self):
        self.create_pm25_entry(60, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)

        self.create_pm25_entry(220, minutes_ago=3)
        self.create_pm25_entry(220, minutes_ago=2)
        self.create_pm25_entry(220, minutes_ago=1)
        u = evaluator.update_check(alert, self.entry_model, self.lookup)

        updates = AlertUpdate.objects.filter(alert=alert)
        # import code
        # code.interact(local=locals())
        assert updates.count() == 2
        assert updates.latest().get_level() > updates.earliest().get_level()

    def test_update_check_ends_alert_when_level_drops_to_good(self):
        # Create entries to trigger an alert (in the last 30 minutes)
        self.create_pm25_entry(80, minutes_ago=25)
        self.create_pm25_entry(80, minutes_ago=20)
        self.create_pm25_entry(80, minutes_ago=15)
        self.create_pm25_entry(80, minutes_ago=10)

        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)

        assert alert is not None

        # Fudge the start_time so the alert is old enough to be ended
        alert.start_time = timezone.now() - timedelta(minutes=90)
        alert.save(update_fields=['start_time'])

        # Now add only GOOD values (simulate air cleaned up)
        self.entry_model.objects.all().delete()
        for i in range(12):
            self.create_pm25_entry(4, minutes_ago=12 - i)
        evaluator.update_check(alert, self.entry_model, self.lookup)

        alert.refresh_from_db()
        assert alert.end_time is not None
        updates = list(alert.updates.order_by('timestamp'))
        assert updates[-1].get_level() == AQLevel.scale.GOOD


    def test_no_update_if_level_has_not_changed(self):
        self.create_pm25_entry(80, minutes_ago=10)
        evaluator = AlertEvaluator(self.monitor)
        evaluator.creation_check(self.entry_model, self.lookup)
        alert = Alert.objects.get(monitor=self.monitor)

        self.create_pm25_entry(80, minutes_ago=1)
        evaluator.update_check(alert, self.entry_model, self.lookup)

        updates = AlertUpdate.objects.filter(alert=alert)
        assert updates.count() == 1

    def test_skips_inactive_monitor_with_no_alert(self):
        self.monitor.is_active = False
        self.monitor.save()

        self.create_pm25_entry(100, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        evaluator.evaluate()

        assert Alert.objects.count() == 0

    def test_alert_and_alertupdate_use_integer_pk_and_sqid(self):
        self.create_pm25_entry(40, minutes_ago=5)
        evaluator = AlertEvaluator(self.monitor)
        alert = evaluator.creation_check(self.entry_model, self.lookup)

        assert isinstance(alert.pk, int)
        assert alert.sqid

        update = alert.updates.first()
        assert isinstance(update.pk, int)
        assert update.sqid


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
        Subscription.objects.create(
            user=unverified_user, monitor=self.monitor, level='moderate',
        )
        update = self.alert.create_update(AQLevel.scale.UNHEALTHY)

        assert not Notification.objects.filter(alert_update=update, user=unverified_user).exists()
