import pytest

from django.test import TestCase
from django.utils import timezone

from camp.api.v2.monitors.serializers import HealthCheckSerializer, MonitorSerializer
from camp.apps.entries import models as entry_models
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.qaqc.models import HealthCheck


pytestmark = [
    pytest.mark.usefixtures('purpleair_monitor'),
    pytest.mark.django_db(transaction=True),
]

class SerializerTests(TestCase):
    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.health_check = HealthCheck.objects.create(
            monitor=self.monitor,
            hour=now - timezone.timedelta(hours=1),
            score=3,
            rpd_pairwise=0.05,
            correlation=0.98,
        )

    def test_health_check_serializer(self):
        data = HealthCheckSerializer(self.health_check).serialize()
        assert data['score'] == self.health_check.score
        assert data['rpd_pairwise'] == self.health_check.rpd_pairwise
        assert data['correlation'] == self.health_check.correlation
        assert data['grade'] == self.health_check.grade
        assert 'hour' in data

    def test_monitor_serializer_includes_health(self):
        self.monitor.health = self.health_check
        data = MonitorSerializer(self.monitor).serialize()
        assert 'health' in data
        assert data['health']['score'] == self.health_check.score
