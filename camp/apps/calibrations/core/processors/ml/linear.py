from decimal import Decimal


from camp.apps.calibrations.models import Calibration
from camp.apps.calibrations.core.processors.base import BaseProcessor
from camp.utils.eval import evaluate_formula


class LinearExpressionProcessor(BaseProcessor):
    required_stage = None
    next_stage = None
    min_required_value = Decimal('5.0')

    def process(self):
        self.calibration = Calibration.objects.get_for_entry(self.entry, self.name)
        value = self.get_correction()

        if value is not None:
            return self.build_entry(
                value=value,
                calibration_id=getattr(self.calibration, 'pk', None),
            )

    def get_correction(self):
        if self.entry.value < self.min_required_value:
            return self.entry.value

        if self.calibration:
            return evaluate_formula(self.calibration.formula, self.context)
