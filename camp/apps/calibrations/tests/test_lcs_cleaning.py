from decimal import Decimal

from django.test import TestCase

from camp.apps.calibrations.core.processors.pm25.lcs import PM25_LCS_Cleaning, cleaning_thresholds


class CleaningTierTests(TestCase):
    """Cleaned PM2.5 data must not change: the spike tiers are pinned here."""

    def cleaner(self):
        return PM25_LCS_Cleaning.__new__(PM25_LCS_Cleaning)

    def test_cleaning_tier_bounds(self):
        assert cleaning_thresholds() == (
            (Decimal('9.0'), None),
            (Decimal('35.4'), 5),
            (Decimal('55.4'), 4),
            (Decimal('125.4'), 3),
            (Decimal('225.4'), 3),
            (Decimal('10000.0'), 3),
        )

    def test_tier_edges(self):
        one = Decimal('1')
        # 9.0 is Good: never cleaned.
        assert self.cleaner().apply_spike_logic(Decimal('9.0'), one, one) == Decimal('9.0')
        # 9.05 falls in Moderate (multiplier 5): a spike over 5x its neighbors is replaced.
        assert self.cleaner().apply_spike_logic(Decimal('9.05'), one, one) == one
        assert self.cleaner().apply_spike_logic(Decimal('9.05'), Decimal('2'), Decimal('2')) == Decimal('9.05')
