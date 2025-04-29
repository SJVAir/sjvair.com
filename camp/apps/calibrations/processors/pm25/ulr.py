from decimal import Decimal as D

from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.models import Calibration
from camp.apps.entries.models import PM25
from camp.utils.eval import evaluate_formula

from ..base import BaseProcessor

__all__ = ['PM25_UnivariateLinearRegression']


class PM25_UnivariateLinearRegression(BaseProcessor):
    entry_model = PM25
    required_context = ['pm25']
    required_stage = PM25.Stage.CLEANED
    next_stage = PM25.Stage.CALIBRATED

    min_required_value = D('5.0')

    def process(self):
        self.calibration = Calibration.objects.get_for_entry(self.entry)
        value = self.get_correction()

        if value is not None:
            return self.build_entry(
                value=value,
                calibration_id=getattr(self.calibration, 'pk', None),
            )

    def get_correction(self):
        if self.entry.value < self.min_required_value:
            # There's a minimum threshold to calibrate,
            # otherwise just return the raw value.
            return self.entry.value

        if self.calibration:
            return evaluate_formula(self.calibration.formula, self.context)

