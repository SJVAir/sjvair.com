import logging

from decimal import Decimal, InvalidOperation

from django.utils.functional import cached_property

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
            return Calibration.objects.get_for_entry(self.entry, self.name)

    def process(self):
        value = self.get_correction()

        if value is not None and not self.is_plausible(value):
            logger.warning(
                '%s: discarding out-of-range value %s for %s %s (calibration=%s)',
                self.name, value, self.entry.__class__.__name__, self.entry.pk,
                getattr(self.calibration, 'pk', None),
            )
            return

        if value is not None:
            return self.build_entry(
                value=value,
                calibration_id=getattr(self.calibration, 'pk', None),
            )

    def get_correction(self):
        if self.calibration is None:
            return

        if self.entry.value <= self.min_required_value:
            return self.entry.value

        if self.calibration:
            return evaluate_formula(self.calibration.formula, self.context)

    def is_plausible(self, value):
        '''
        True if `value` is within the entry model's plausible_range and fits
        the `value` column, so a bad regression can't raise a DB overflow.
        '''
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            return False
        if not value.is_finite():
            return False

        low, high = self.entry.plausible_range or (None, None)
        if low is not None and value < low:
            return False
        if high is not None and value > high:
            return False

        field = self.entry._meta.get_field('value')
        limit = Decimal(10) ** (field.max_digits - field.decimal_places)
        return abs(value) < limit
