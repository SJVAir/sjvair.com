from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir


class ProcessorTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_processor_equality_and_string_repr(self):
        proc_class = processors.PM25_UnivariateLinearRegression
        proc_name = 'PM25_UnivariateLinearRegression'

        assert str(proc_class) == proc_name == proc_class.name
        assert proc_class == proc_name
        assert proc_class == proc_class
        assert proc_class != 'SomeOtherProcessor'

    def test_processor_filtering_by_class(self):
        now = timezone.now()
        pm25_entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=now,
            value=Decimal('12.5'),
            stage=entry_models.PM25.Stage.CALIBRATED,
            processor=processors.PM25_UnivariateLinearRegression
        )

        pm25_entry.refresh_from_db()
        assert pm25_entry.processor == processors.PM25_UnivariateLinearRegression
        assert pm25_entry.processor == processors.PM25_UnivariateLinearRegression.name

        result = entry_models.PM25.objects.filter(
            stage=entry_models.PM25.Stage.CALIBRATED,
            processor=processors.PM25_UnivariateLinearRegression
        )
        assert pm25_entry in result

        empty = entry_models.PM25.objects.filter(
            processor=processors.PM25_EPA_Oct2021
        )
        assert empty.exists() == False

    def test_processor_filter_via_entry_config_alerts(self):
        now = timezone.now()

        # Create a calibrated entry using the expected processor
        entry = entry_models.PM25.objects.create(
            monitor=self.monitor,
            timestamp=now,
            value=Decimal('35.2'),
            stage=self.monitor.ENTRY_CONFIG[entry_models.PM25]['alerts']['stage'],
            processor=self.monitor.ENTRY_CONFIG[entry_models.PM25]['alerts']['processor']
        )

        # Now use the alert config to filter for that entry
        qs = entry_models.PM25.objects.filter(**self.monitor.ENTRY_CONFIG[entry_models.PM25]['alerts'])
        assert entry in qs

    def test_pm25_lcs_cleaning(self):
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
                stage=entry_models.PM25.Stage.CORRECTED
            )
            entry.refresh_from_db()
            raw_entries.append(entry)

        # Run the cleaner on the spiked entry
        spike_idx = values.index(max(values))
        spike = raw_entries[spike_idx]
        cleaner = processors.PM25_LCS_Cleaning(spike)
        cleaned = cleaner.run()

        assert cleaned is not None, 'Cleaner returned no output'
        assert cleaned.stage == entry_models.PM25.Stage.CLEANED
        assert cleaned.value == max([
            raw_entries[spike_idx - 1].value,
            raw_entries[spike_idx + 1].value
        ])
        assert cleaned.value < spike.value, 'Spike was not reduced'

    def test_pm25_lcs_correction_high_variance(self):
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
        cleaner = processors.PM25_LCS_Correction(a_entry)
        cleaned = cleaner.run()

        assert cleaned is not None
        assert cleaned.stage == entry_models.PM25.Stage.CORRECTED

        # Variance pct = ((50-10)^2 / 2) / 30 * 100 = ~26.6%
        # Should return the **lower** value (min of a/b)
        assert cleaned.value == b_entry.value

    def test_pm25_lcs_correction_low_variance(self):
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

        cleaner = processors.PM25_LCS_Correction(a_entry)
        cleaned = cleaner.run()

        assert cleaned is not None
        expected = (a_entry.value + b_entry.value) / 2
        assert cleaned.value == expected

    def test_pm25_epa_oct2021(self):
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

        correction = processors.PM25_EPA_Oct2021(pm25)
        assert correction.is_valid()

        calibrated = correction.run()
        assert calibrated is not None
        assert calibrated.value != pm25.value
        assert calibrated.stage == entry_models.PM25.Stage.CALIBRATED
        assert calibrated.processor == correction.name
        assert calibrated.monitor == self.monitor

    def test_fem_cleaner_discards_invalid(self):
        monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        now = timezone.now()

        # Should be discarded (< -10)
        entry = entry_models.PM25.objects.create(
            monitor=monitor,
            timestamp=now,
            value=Decimal('-15'),
            stage=entry_models.PM25.Stage.RAW
        )
        assert processors.PM25_FEM_Cleaner(entry).run() is None

    def test_fem_cleaner_clamps_to_zero(self):
        monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        now = timezone.now()

        # Should be clamped to 0
        entry = entry_models.PM25.objects.create(
            monitor=monitor,
            timestamp=now,
            value=Decimal('-5'),
            stage=entry_models.PM25.Stage.RAW
        )
        cleaned = processors.PM25_FEM_Cleaner(entry).run()
        assert cleaned is not None
        assert cleaned.value == 0
        assert cleaned.stage == entry_models.PM25.Stage.CLEANED

    def test_fem_cleaner_passes_valid(self):
        monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        now = timezone.now()

        # Should pass through
        entry = entry_models.PM25.objects.create(monitor=monitor, timestamp=now, value=Decimal('12.5'), stage=entry_models.PM25.Stage.RAW)
        cleaned = processors.PM25_FEM_Cleaner(entry).run()
        assert cleaned is not None
        assert cleaned.value == entry.value
        assert cleaned.stage == entry_models.PM25.Stage.CLEANED
