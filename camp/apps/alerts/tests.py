import pytest

from django.test import TestCase
from django.core.exceptions import ValidationError

from camp.apps.accounts.models import User
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25, Particulates
from camp.apps.alerts.models import Subscription


class SubscriptionModelTest(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.user = User.objects.get()
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_valid_subscription_saves(self):
        sub = Subscription(
            user_id=self.user.pk,
            monitor_id=self.monitor.pk,
            entry_type=PM25.entry_type,
            level=PM25.Levels.UNHEALTHY_SENSITIVE.key.upper(),  # should get coerced to lowercase
        )
        sub.clean()  # triggers validation
        sub.save()
        assert Subscription.objects.count() == 1
        assert Subscription.objects.first().level == PM25.Levels.UNHEALTHY_SENSITIVE.key

    def test_invalid_level_raises_validation_error(self):
        sub = Subscription(
            user_id=self.user.pk,
            monitor_id=self.monitor.pk,
            entry_type=PM25.entry_type,
            level='ridiculously_high'
        )
        with pytest.raises(ValidationError, match='not a valid alert level'):
            sub.clean()

    def test_entry_type_without_levels_raises_error(self):
        sub = Subscription(
            user=self.user,
            monitor=self.monitor,
            entry_type=Particulates.entry_type,
            level='moderate'
        )
        with pytest.raises(ValidationError, match='does not support alert levels'):
            sub.clean()
