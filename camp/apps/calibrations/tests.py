from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.purpleair.models import PurpleAir
from . import cleaners, corrections


class CalibrationTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_pm25_lcs_cleaner(self):
        base_time = timezone.now() - timedelta(hours=1)

        # Create a spike-y raw time series
        timestamps = [base_time + timedelta(minutes=i) for i in range(6)]
        values = [10, 10, 12, 13, 90, 11, 12, 10]  # The '90' is the spike to be smoothed

        raw_entries = []
        for ts, val in zip(timestamps, values):
            entry = entry_models.PM25.objects.create(
                monitor=self.monitor,
                timestamp=ts,
                sensor='a',
                value=Decimal(val),
                position=self.monitor.position,
                location=self.monitor.location,
                stage=entry_models.PM25.Stage.RAW
            )
            entry.refresh_from_db()
            raw_entries.append(entry)

        # Run the cleaner on the spiked entry
        spike_idx = values.index(max(values))
        spike = raw_entries[spike_idx]
        cleaner = cleaners.PM25LowCostSensor(spike)
        cleaned = cleaner.run()

        assert cleaned is not None, 'Cleaner returned no output'
        assert cleaned.stage == entry_models.PM25.Stage.CLEANED
        assert cleaned.value == max([
            raw_entries[spike_idx - 1].value,
            raw_entries[spike_idx + 1].value
        ])
        assert cleaned.value < spike.value, 'Spike was not reduced'

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

        correction = corrections.EPA_PM25_Oct2021(pm25)
        assert correction.is_valid()

        calibrated = correction.run()
        assert calibrated is not None
        assert calibrated.value != pm25.value
        assert calibrated.stage == entry_models.PM25.Stage.CALIBRATED
        assert calibrated.calibration == correction.name
        assert calibrated.monitor == self.monitor