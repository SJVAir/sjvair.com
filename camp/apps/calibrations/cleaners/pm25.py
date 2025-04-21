from decimal import Decimal

from camp.apps.entries.models import PM25
from .base import BaseCleaner

__all__ = ['PM25LowCostSensor']


class PM25LowCostSensor(BaseCleaner):
    '''
    Cleans PM2.5 entries from low-cost dual-sensor monitors using
    spike smoothing and repetition filtering.

    Returns a cleaned clone of the original entry, or None if the entry
    should be discarded as invalid or repeated.
    '''

    entry_model = PM25

    def process(self):
        if (self.entry.value is None
            or self.entry.value < -15
            or self.entry.value > 3000
        ):
            return None  # Clearly invalid

        if self.is_repeated():
            return None  # Filter out repeated sequences
        
        cleaned_value = self.compute_ab_adjusted_value()

        # cleaned_value = self.entry.value
        prev = self.entry.get_previous_entry()
        next_ = self.entry.get_next_entry()

        if prev and next_:
            cleaned_value = self.apply_spike_logic(
                current_value=cleaned_value,
                prev_value=prev.value,
                next_value=next_.value,
            )

        # If the cleaned value is less than 0, set it to 0.
        cleaned_value = max(cleaned_value, 0)

        return self.build_entry(value=cleaned_value)

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
        sibling = self.entry.get_sibling_entries().first()

        if not sibling:
            return current_value

        a = self.entry.value
        b = sibling.value

        average = (a + b) / 2
        variance = ((a - b) ** 2) / 2
        variance_pct = (variance / average) * 100 if average != 0 else Decimal(0)

        if variance_pct <= 10:
            return average
        else:
            return min(a, b)

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