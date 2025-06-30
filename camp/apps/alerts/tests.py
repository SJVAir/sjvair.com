from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from camp.apps.alerts.models import Alert, AlertUpdate
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.entries.models import PM25
from camp.apps.entries.levels import AQLevel, LevelSet
from camp.apps.monitors.purpleair.models import PurpleAir


class AlertEvaluatorTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)
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
        assert alerts.first().entry_type == self.entry_model.entry_type

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
