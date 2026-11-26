import logging

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils.functional import cached_property

from camp.apps.calibrations.lookup import active_lookup
from camp.apps.calibrations.models import Calibration
from camp.apps.calibrations.core.processors.base import BaseProcessor
from camp.utils.eval import evaluate_formula

logger = logging.getLogger(__name__)


class LinearExpressionProcessor(BaseProcessor):
    required_stage = None
    next_stage = None
    min_required_value = Decimal('5.0')

    @cached_property
    def calibration(self):
        if self.entry.position:
            # Bulk reprocessing activates a per-chunk lookup (see lookup.py).
            if (lookup := active_lookup()) is not None:
                return lookup.get_for_entry(self.entry, self.name)
            return Calibration.objects.get_for_entry(self.entry, self.name)

    def process(self):
        value = self.get_correction()
        if value is None:
            return

        bounded = self.bound(value)
        if bounded is None:
            logger.warning(
                '%s: discarding out-of-range value %s for %s %s (calibration=%s)',
                self.name, value, self.entry.__class__.__name__, self.entry.pk,
                getattr(self.calibration, 'pk', None),
            )
            return

        return self.build_entry(
            value=bounded,
            calibration_id=getattr(self.calibration, 'pk', None),
        )

    def get_correction(self):
        if self.calibration is None:
            return

        if self.entry.value <= self.min_required_value:
            return self.entry.value

        if self.calibration:
            return evaluate_formula(self.calibration.formula, self.context)

    def bound(self, value):
        '''
        `value` fitted to the entry model's plausible_range, or None if it
        can't be stored. Below the minimum is clamped to it (a regression
        can dip under 0 in clean air, and every other PM2.5 step clamps
        negatives to 0 too). Above the maximum, not a finite number, or too
        large for the `value` column once rounded to its decimal places is
        discarded, so a bad regression can't raise a DB overflow.
        '''
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            return None
        if not value.is_finite():
            return None

        low, high = self.entry.plausible_range or (None, None)
        if low is not None and value < low:
            value = low
        if high is not None and value > high:
            return None

        # Postgres rounds to the column's scale before checking precision.
        field = self.entry._meta.get_field('value')
        rounded = value.quantize(Decimal(1).scaleb(-field.decimal_places), rounding=ROUND_HALF_UP)
        if abs(rounded) >= Decimal(10) ** (field.max_digits - field.decimal_places):
            return None
        return value
