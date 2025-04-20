from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.purpleair.models import PurpleAir
from .corrections.pm25 import EPA_PM25_Oct2021


class TestEPAPM25Calibration(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)
        self.correction = EPA_PM25_Oct2021

    def test_epa_pm25_calibration(self):
        now = timezone.now()
        
        entry_models.Humidity.objects.create(
            monitor=self.monitor,
            timestamp=now,
            sensor='a',
            value=Decimal('45.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW
        )

        pm25 = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=now,
            sensor='a',
            value=Decimal('15.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.CLEANED
        )

        correction = EPA_PM25_Oct2021(pm25)
        assert correction.is_valid()

        calibrated = correction.run()
        assert calibrated is not None
        assert calibrated.value != pm25.value
        assert calibrated.calibration == 'EPA_PM25_Oct2021'
        assert calibrated.monitor == self.monitor