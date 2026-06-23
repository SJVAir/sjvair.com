from datetime import timedelta

from django.db.models import Avg

from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.base import BaseProcessor
from camp.apps.entries.models import O3

__all__ = ['AQLiteRawCleaner', 'AQLiteHourlyAggregator']

# Drop readings outside these bounds before aggregation.
# Negatives in [-10, 0) are valid near-zero noise — keep them signed so the
# hourly mean stays unbiased. Clamp happens only in the aggregator, after averaging.
MIN_VALID = -10   # ppb — below this is an instrument fault, not noise
MAX_VALID = 500   # ppb — FEM certification boundary; comfortably above real SJV peaks

# A gap longer than this between consecutive RAW entries implies a restart.
GAP_THRESHOLD = timedelta(minutes=30)

# How long after a detected restart to discard readings while the lamp stabilizes.
WARMUP_DURATION = timedelta(minutes=20)


@processors.register()
class AQLiteRawCleaner(BaseProcessor):
    entry_model = O3
    required_stage = O3.Stage.RAW
    next_stage = O3.Stage.CLEANED

    def process(self):
        if self.entry.value is None:
            return None

        if self.entry.value < MIN_VALID or self.entry.value >= MAX_VALID:
            return None

        if self._in_warmup():
            return None

        # Pass signed value through unchanged — do NOT clamp here.
        # The hourly aggregator averages signed values to keep the mean unbiased,
        # then clamps the result to 0 for display.
        return self.build_entry(value=self.entry.value)

    def _in_warmup(self):
        """
        True if this entry falls within WARMUP_DURATION of a detected restart.

        Looks back WARMUP_DURATION in the RAW history plus one entry before that
        window to detect any gap > GAP_THRESHOLD. If a gap is found, the first
        entry after it is treated as t=0 of the warmup period.
        """
        window_start = self.entry.timestamp - WARMUP_DURATION

        entries_in_window = list(
            O3.objects
            .filter(
                monitor=self.entry.monitor,
                stage=O3.Stage.RAW,
                timestamp__gte=window_start,
                timestamp__lt=self.entry.timestamp,
            )
            .order_by('timestamp')
            .values_list('timestamp', flat=True)
        )

        prev_before_window = (
            O3.objects
            .filter(
                monitor=self.entry.monitor,
                stage=O3.Stage.RAW,
                timestamp__lt=window_start,
            )
            .order_by('-timestamp')
            .values_list('timestamp', flat=True)
            .first()
        )

        all_timestamps = ([prev_before_window] if prev_before_window else []) + entries_in_window

        # Scan for any gap > GAP_THRESHOLD; record the restart timestamp (entry after gap).
        restart_at = None
        for i in range(1, len(all_timestamps)):
            if all_timestamps[i] - all_timestamps[i - 1] > GAP_THRESHOLD:
                restart_at = all_timestamps[i]

        # Also check the gap from the last known entry to this entry.
        if all_timestamps:
            if self.entry.timestamp - all_timestamps[-1] > GAP_THRESHOLD:
                restart_at = self.entry.timestamp
        else:
            # No history at all — this is the very first entry ever recorded.
            return False

        if restart_at is None:
            return False

        return (self.entry.timestamp - restart_at) < WARMUP_DURATION


@processors.register()
class AQLiteHourlyAggregator:
    """
    Aggregates one hour of CLEANED O3 entries into a single CALIBRATED value.

    Not a per-entry processor — invoked directly by the hourly Huey task.
    Registered in the processor registry so DefaultCalibration can reference it
    by name and update_latest_entry will recognise it as the display value.
    """

    name = 'AQLiteHourlyAggregator'
    entry_model = O3
    next_stage = O3.Stage.CALIBRATED

    @classmethod
    def aggregate(cls, monitor, hour_start, hour_end):
        result = (
            O3.objects
            .filter(
                monitor=monitor,
                stage=O3.Stage.CLEANED,
                timestamp__gte=hour_start,
                timestamp__lt=hour_end,
            )
            .aggregate(mean=Avg('value'))
        )

        mean = result['mean']
        if mean is None:
            return None

        # Clamp to 0 here — after averaging signed values — so the mean is unbiased
        # but the displayed value is never negative.
        value = max(mean, 0)

        entry = monitor.create_entry(
            O3,
            timestamp=hour_start,
            stage=O3.Stage.CALIBRATED,
            processor=cls.name,
            value=value,
            save=False,
        )

        if entry:
            entry.save()
            entry.refresh_from_db()
            monitor.update_latest_entry(entry)
            return entry
