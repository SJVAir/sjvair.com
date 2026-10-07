import math
import random
from collections import Counter
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from waffle.testutils import override_flag

from camp.apps.accounts.models import User
from camp.apps.alerts import notifications, tasks
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification, Subscription
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


@override_flag('sms_alerts', active=True)
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
                    # Raw entry creation doesn't update LatestEntry, which is_active reads.
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
        assert sent
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

    def test_episodic_smoke_is_capped_per_day(self):
        # 40 minutes of smoke every 3 hours.
        sent = self.run_trace(lambda m: 60 if m % 180 < 40 else 5, hours=24)
        assert sent
        per_day = Counter(
            at.astimezone(PACIFIC).date() for at, kind, level in sent if kind == Notification.Kind.ALERT
        )
        assert all(count <= notifications.DAILY_CAP for count in per_day.values()), per_day
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_unhealthy_episodic_smoke_is_capped_per_day(self):
        sent = self.run_trace(lambda m: 100 if m % 180 < 40 else 5, hours=24)
        assert sent
        per_day = Counter(
            at.astimezone(PACIFIC).date() for at, kind, level in sent if kind == Notification.Kind.ALERT
        )
        assert all(count <= notifications.DAILY_CAP for count in per_day.values()), per_day
        self.assert_spacing(sent)
        self.assert_daily_volume(sent)

    def test_one_bad_reading_per_hour_never_texts(self):
        sent = self.run_trace(lambda m: 400 if m % 60 == 0 else 6, hours=24)
        assert sent == []
        # Positive control: the evaluator ran and saw the brief spikes.
        assert Alert.objects.filter(monitor=self.monitor, entry_type=PM25.entry_type).exists()

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
