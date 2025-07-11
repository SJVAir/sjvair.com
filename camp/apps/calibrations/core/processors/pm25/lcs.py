from datetime import timedelta
from decimal import Decimal

from camp.apps.entries.models import PM25

from camp.apps.calibrations import processors
from ..base import BaseProcessor

__all__ = ['PM25_LCS_Correction', 'PM25_LCS_Cleaning']


@processors.register()
class PM25_LCS_Correction(BaseProcessor):
    '''
    Cleans PM2.5 entries from low-cost dual-sensor monitors using
    repetition and A/B variance filtering.

    Returns a cleaned clone of the original entry, or None if the entry
    should be discarded as invalid or is repeated.
    '''

    entry_model = PM25
    required_stage = PM25.Stage.RAW
    next_stage = PM25.Stage.CORRECTED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sibling = self.entry.get_sibling_entry()

    def is_valid(self):
        # Standard validation first
        if not super().is_valid():
            return False

        if self.sibling:
            # Use lexical order of sensor names to decide who runs correction
            my_sensor = self.entry.sensor or ''
            sib_sensor = self.sibling.sensor or ''

            if sib_sensor < my_sensor:
                # Let the sibling handle correction
                return False
        return True

    def process(self):
        if (self.entry.value is None
            or self.entry.value < -15
            or self.entry.value > 3000
        ):
            # Clearly invalid
            return

        if self.is_repeated():
            # Filter out repeated sequences
            return

        cleaned_value = self.compute_ab_adjusted_value()
        cleaned_value = max(cleaned_value, 0)
        return self.build_entry(
            value=cleaned_value,
            sensor='', # At this point, A and B are effectively merged.
        )

    def is_repeated(self, max_repeat=5) -> bool:
        '''
        Checks whether the given entry is part of a sequence of repeated values.

        A value is considered repeated if it appears at least `max_repeat`
        consecutive times across the same sensor (looking both backward and forward).

        Args:
            entry (PM25): The raw PM2.5 entry to evaluate.
            max_repeat (int): The number of repeated values required to consider it a repeat.

        Returns:
            bool: True if the value is part of a repeated sequence, False otherwise.
        '''
        value = self.entry.value

        prev_values = list(self.entry
            .get_previous_entries()
            .values_list('value', flat=True)[:max_repeat]
        )
        next_values = list(self.entry
            .get_next_entries()
            .values_list('value', flat=True)[:max_repeat]
        )

        repeat_count = 1
        repeat_count += sum(1 for v in prev_values if v == value)
        repeat_count += sum(1 for v in next_values if v == value)

        return repeat_count > max_repeat

    def compute_ab_adjusted_value(self) -> Decimal:
        '''
        Computes cleaned value using a/b sensor logic.

        - If both A and B exist:
            - use average if variance_pct ≤ 10
            - use min(a, b) if variance_pct > 10
        - If only one exists, use that value
        - If neither, return self.entry.value
        '''
        current_value = self.entry.value

        if not self.sibling:
            return current_value

        a = self.entry.value
        b = self.sibling.value

        average = (a + b) / 2
        variance = ((a - b) ** 2) / 2
        variance_pct = (variance / average) * 100 if average != 0 else Decimal(0)

        if variance_pct <= 10:
            return average
        return min(a, b)


@processors.register()
class PM25_LCS_Cleaning(BaseProcessor):
    '''
    Applies spike detection and smoothing to corrected PM2.5 entries
    from low-cost dual-sensor monitors (e.g., PurpleAir).

    This processor expects the input entry to be in the 'corrected' stage
    (i.e., A/B variance already applied) and returns a new entry in the
    'cleaned' stage. If sufficient nearby data is available, it may adjust
    the value to smooth out spikes based on AQI-aware thresholds.
    '''

    entry_model = PM25
    required_stage = PM25.Stage.CORRECTED
    next_stage = PM25.Stage.CLEANED

    def process(self):
        '''
        Applies spike smoothing to a corrected PM2.5 entry if both previous and
        next entries are available and occur within a valid time window.

        If the next entry is missing (i.e., this is the latest known entry),
        spike detection is deferred and no CLEANED entry is returned yet.

        If both the previous and next entries are present and occur within
        an acceptable time window, the current value is evaluated for spikes
        and may be adjusted. If adjacent entries are missing or too far apart,
        the value is returned unchanged.

        Returns:
            A new CLEANED entry with the smoothed or unchanged value, or None if
            spike detection must be deferred due to missing next entry.
        '''
        next_entry = self.entry.get_next_entry()
        if next_entry is None:
            return

        prev_entry = self.entry.get_previous_entry()
        cleaned_value = self.entry.value

        if prev_entry and next_entry:
            prev_gap_valid = self.valid_time_gap(prev_entry, self.entry)
            next_gap_valid = self.valid_time_gap(self.entry, next_entry)
            if prev_gap_valid and next_gap_valid:
                cleaned_value = self.apply_spike_logic(
                    current_value=cleaned_value,
                    prev_value=prev_entry.value,
                    next_value=next_entry.value,
                )

        return self.build_entry(value=cleaned_value)

    def valid_time_gap(self, entry_a, entry_b, max_gap=timedelta(minutes=20)) -> bool:
        '''
        Returns True if the time between entry_a and entry_b is within max_gap.
        Used to ensure spike detection isn't applied across unusually large gaps.
        '''
        if not entry_a or not entry_b:
            return False
        return abs(entry_a.timestamp - entry_b.timestamp) <= max_gap

    def apply_spike_logic(self, current_value, prev_value, next_value) -> Decimal:
        '''
        Cleans PM2.5 spikes based on AQI-aware thresholds using Decimal for precision.

        Parameters:
            current_value (Decimal): PM2.5 value at the current timestamp
            prev_value (Decimal): PM2.5 value from the previous timestamp
            next_value (Decimal): PM2.5 value from the next timestamp

        Returns:
            Decimal: Cleaned PM2.5 value
        '''
        thresholds = [
            (Decimal('9.0'), None), # Good
            (Decimal('35.4'), 5), # Moderate
            (Decimal('55.4'), 4), # USG
            (Decimal('125.4'), 3), # Unhealthy
            (Decimal('225.4'), 3), # Very Unhealthy
            (Decimal('10000.0'), 3), # Hazardous fallback
        ]

        threshold = None
        for max_pm, multiplier in thresholds:
            if current_value <= max_pm:
                threshold = multiplier
                break

        if threshold is None:
            return current_value

        avg_neighbors = (prev_value + next_value) / 2

        if current_value > (avg_neighbors * threshold):
            return max(prev_value, next_value)

        return current_value
