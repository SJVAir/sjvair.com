from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.o3.aqlite import AQLiteHourlyAggregator
from camp.apps.entries.models import O3
from camp.apps.monitors.aqlite.models import AQLite


def make_monitor():
    return AQLite.objects.create(
        name='Test AQLite',
        device_id='AQLite-TEST',
        position=Point(-119.8, 36.7),
        location='outside',
    )


def make_raw(monitor, timestamp, value):
    return O3.objects.create(
        monitor=monitor,
        timestamp=timestamp,
        value=value,
        stage=O3.Stage.RAW,
        position=monitor.position,
        location=monitor.location,
    )


def make_cleaned(monitor, timestamp, value):
    return O3.objects.create(
        monitor=monitor,
        timestamp=timestamp,
        value=value,
        stage=O3.Stage.CLEANED,
        position=monitor.position,
        location=monitor.location,
    )


class AQLiteRawCleanerTests(TestCase):
    def setUp(self):
        self.monitor = make_monitor()
        self.now = timezone.now().replace(second=0, microsecond=0)

    def _clean(self, value, history=None):
        """Create a RAW entry at self.now and run the cleaner on it."""
        for ts, v in (history or []):
            make_raw(self.monitor, ts, v)
        entry = make_raw(self.monitor, self.now, value)
        entry.refresh_from_db()
        return processors.AQLiteRawCleaner(entry).run()

    # --- Range checks ---

    def test_discards_at_ceiling(self):
        assert self._clean(1000) is None

    def test_discards_above_ceiling(self):
        assert self._clean(1001) is None

    def test_discards_below_floor(self):
        assert self._clean(-11) is None

    def test_passes_at_floor(self):
        # -10 is exactly MIN_VALID — should pass
        history = [(self.now - timedelta(minutes=i * 5), 5) for i in range(1, 8)]
        result = self._clean(-10, history=history)
        assert result is not None
        assert result.stage == O3.Stage.CLEANED
        assert float(result.value) == -10.0

    def test_does_not_clamp_negative_noise(self):
        # Values in [-10, 0) must pass through SIGNED — no clamp before aggregation.
        history = [(self.now - timedelta(minutes=i * 5), 5) for i in range(1, 8)]
        result = self._clean(-3, history=history)
        assert result is not None
        assert float(result.value) == -3.0

    def test_passes_valid_positive(self):
        history = [(self.now - timedelta(minutes=i * 5), 5) for i in range(1, 8)]
        result = self._clean(42, history=history)
        assert result is not None
        assert result.stage == O3.Stage.CLEANED
        assert float(result.value) == 42.0

    # --- Warmup detection ---

    def test_first_entry_ever_not_in_warmup(self):
        # No history at all — should pass through (can't detect a restart).
        result = self._clean(5)
        assert result is not None

    def test_no_gap_not_in_warmup(self):
        # Continuous 5-minute history, no gap.
        history = [(self.now - timedelta(minutes=i * 5), 5) for i in range(1, 10)]
        result = self._clean(5, history=history)
        assert result is not None

    def test_first_entry_after_gap_dropped(self):
        # One entry 35 min ago, then this entry — gap of 35 min implies restart.
        history = [(self.now - timedelta(minutes=35), 5)]
        result = self._clean(5, history=history)
        assert result is None

    def test_entry_in_warmup_window_dropped(self):
        # Restart 10 minutes ago — this entry is 10 min post-restart, still warming up.
        history = [
            (self.now - timedelta(minutes=45), 5),   # before the gap
            (self.now - timedelta(minutes=10), 5),   # first entry after restart (35-min gap > 10-min threshold)
        ]
        result = self._clean(5, history=history)
        assert result is None

    def test_entry_past_warmup_not_dropped(self):
        # Restart 25 min ago — past the 20-min warmup window.
        restart = self.now - timedelta(minutes=25)
        history = [(self.now - timedelta(minutes=60), 5)]  # pre-gap anchor
        history += [(restart + timedelta(minutes=i * 5), 5) for i in range(5)]  # post-restart
        result = self._clean(5, history=history)
        assert result is not None
        assert result.stage == O3.Stage.CLEANED


class AQLiteHourlyAggregatorTests(TestCase):
    def setUp(self):
        self.monitor = make_monitor()
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.hour_end = now
        self.hour_start = now - timedelta(hours=1)

    def _populate(self, values):
        for i, v in enumerate(values):
            make_cleaned(self.monitor, self.hour_start + timedelta(minutes=i * 5), v)

    def test_no_data_returns_none(self):
        result = AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert result is None

    def test_aggregates_mean(self):
        self._populate([2, 4, -2, 8])  # mean = 3.0
        entry = AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert entry is not None
        assert entry.stage == O3.Stage.CALIBRATED
        assert entry.processor == 'AQLiteHourlyAggregator'
        assert entry.timestamp == self.hour_start
        assert float(entry.value) == 3.0

    def test_clamps_negative_mean_to_zero(self):
        self._populate([-3, -1])  # mean = -2.0, clamped to 0
        entry = AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert entry is not None
        assert float(entry.value) == 0.0

    def test_does_not_duplicate(self):
        self._populate([5, 5, 5])
        first = AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert first is not None
        second = AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert second is None
        assert O3.objects.filter(monitor=self.monitor, stage=O3.Stage.CALIBRATED).count() == 1

    def test_updates_latest_entry(self):
        from camp.apps.monitors.models import LatestEntry
        self._populate([10, 10])
        AQLiteHourlyAggregator.aggregate(self.monitor, self.hour_start, self.hour_end)
        assert LatestEntry.objects.filter(
            monitor=self.monitor,
            entry_type='o3',
            stage=O3.Stage.CALIBRATED,
            processor='AQLiteHourlyAggregator',
        ).exists()


class AQLitePipelineTests(TestCase):
    def setUp(self):
        self.monitor = make_monitor()
        self.now = timezone.now().replace(second=0, microsecond=0)
        # Seed enough history so the cleaner doesn't think we're in warmup.
        for i in range(1, 10):
            make_raw(self.monitor, self.now - timedelta(minutes=i * 5), 5)

    def test_raw_entry_produces_cleaned(self):
        entry = make_raw(self.monitor, self.now, 15)
        entry.refresh_from_db()
        results = self.monitor.process_entry_pipeline(entry)
        cleaned = [e for e in results if e.stage == O3.Stage.CLEANED]
        assert len(cleaned) == 1
        assert float(cleaned[0].value) == 15.0

    def test_invalid_raw_entry_produces_no_cleaned(self):
        entry = make_raw(self.monitor, self.now, 1000)
        entry.refresh_from_db()
        results = self.monitor.process_entry_pipeline(entry)
        assert not any(e.stage == O3.Stage.CLEANED for e in results)
