from decimal import Decimal as D

from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.models import Calibrator
from camp.apps.entries.models import PM25

from ..base import BaseProcessor

__all__ = ['PM25_UnivariateLinearRegression']


class PM25_UnivariateLinearRegression(BaseProcessor):
    entry_model = PM25
    required_context = ['pm25']
    required_stage = PM25.Stage.CLEANED
    next_stage = PM25.Stage.CALIBRATED

    min_required_value = D('5.0')

    def process(self):
        value = self.get_correction()
        if value is not None:
            return self.build_entry(value=value)

    def get_correction(self):
        if self.entry.value < self.min_required_value:
            # There's a minimum threshold to calibrate,
            # otherwise just return the raw value.
            return self.entry.value

        if formula := self.get_calibration_formula():
            parser = ExpressionParser()
            expression = parser.parse(formula)
            return expression.evaluate(self.context)

    def get_calibration_formula(self):
        calibrator = (Calibrator.objects
            .filter(is_enabled=True)
            .exclude(calibration__isnull=True)
            .select_related('calibration')
            .closest(self.entry.monitor.position)
        )

        if calibrator is not None:
            calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
            if calibration is not None:
                return calibration.formula
