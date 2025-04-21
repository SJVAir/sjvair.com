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

    def test_pm25_lcs_cleaner_spike(self):
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

    def test_pm25_lcs_cleaner_ab_high_variance(self):
        base_time = timezone.now() - timedelta(minutes=5)

        ts = base_time.replace(second=0, microsecond=0)

        # Sensor 'a' has a high value, 'b' has a low value → high variance
        a_entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=ts,
            sensor='a',
            value=Decimal('50.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW
        )
        b_entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=ts,
            sensor='b',
            value=Decimal('10.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW
        )

        a_entry.refresh_from_db()
        b_entry.refresh_from_db()

        # Clean the 'a' entry
        cleaner = cleaners.PM25LowCostSensor(a_entry)
        cleaned = cleaner.run()

        assert cleaned is not None
        assert cleaned.stage == entry_models.PM25.Stage.CLEANED

        # Variance pct = ((50-10)^2 / 2) / 30 * 100 = ~26.6%
        # Should return the **lower** value (min of a/b)
        assert cleaned.value == b_entry.value

    def test_pm25_lcs_cleaner_ab_low_variance(self):
        base_time = timezone.now() - timedelta(minutes=5)
        ts = base_time.replace(second=0, microsecond=0)

        a_entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=ts,
            sensor='a',
            value=Decimal('25.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW
        )
        b_entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=ts,
            sensor='b',
            value=Decimal('26.0'),
            position=self.monitor.position,
            location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW
        )

        a_entry.refresh_from_db()
        b_entry.refresh_from_db()

        cleaner = cleaners.PM25LowCostSensor(a_entry)
        cleaned = cleaner.run()

        assert cleaned is not None
        expected = (a_entry.value + b_entry.value) / 2
        assert cleaned.value == expected

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