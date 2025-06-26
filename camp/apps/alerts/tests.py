import pytest

from django.test import TestCase
from django.core.exceptions import ValidationError

from camp.apps.accounts.models import User
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries import models as entry_models
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
            level=entry_models.PM25.Levels.UNHEALTHY_SENSITIVE.key.upper(),  # should get coerced to lowercase
        )
        sub.clean()  # triggers validation
        sub.save()
        assert Subscription.objects.count() == 1
        assert Subscription.objects.first().level == entry_models.PM25.Levels.UNHEALTHY_SENSITIVE.key
