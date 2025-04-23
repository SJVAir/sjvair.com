from datetime import timedelta
from decimal import Decimal

from camp.apps.entries.models import PM25

from ..base import BaseProcessor

__all__ = ['PM25_LCS_Cleaner']


class PM25_LCS_Cleaner(BaseProcessor):
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
        Applies spike smoothing logic to the current corrected entry.

        If both the previous and next entries are present and occur within 
        an acceptable time window, the current value is evaluated for spikes 
        and may be adjusted. If adjacent entries are missing or too far apart, 
        the value is returned unchanged.

        Returns:
            A new PM2.5 entry in the CLEANED stage. The value may be adjusted 
            for spikes or left unchanged if smoothing is not applicable.
        '''
        cleaned_value = self.entry.value
        prev = self.entry.get_previous_entry()
        next_ = self.entry.get_next_entry()

        if prev and next_:
            prev_gap_valid = self.valid_time_gap(prev, self.entry)
            next_gap_valid = self.valid_time_gap(self.entry, next_)
            if prev_gap_valid and next_gap_valid:
                cleaned_value = self.apply_spike_logic(
                    current_value=cleaned_value,
                    prev_value=prev.value,
                    next_value=next_.value,
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
