from decimal import Decimal as D

from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.models import Calibrator
from camp.apps.calibrations.corrections.base import BaseCalibration
from camp.apps.entries.models import PM25

__all__ = ['EPA_PM25_Oct2021', 'Coloc_PM25_LinearRegression']


class EPA_PM25_Oct2021(BaseCalibration):
    '''
    EPA's October 2021 PurpleAir correction algorithm,
    as described in the Fire and Smoke Map documentation.

    https://document.airnow.gov/airnow-fire-and-smoke-map-questions-and-answers.pdf
    '''
    requires = ['pm25', 'humidity']
    entry_model = PM25

    def process(self):
        value = self.get_correction(pm25=self.context['pm25'], rh=self.context['humidity'])
        if value is not None:
            return self.build_entry(value=value)
    
    def get_correction(self, pm25, rh):
        '''
        This function applies different formulas based on the raw PM2.5 reading (pm25).
        'rh' is the relative humidity in percent (0–100).

        Equations (pseudo-code from EPA PDF):
        1) if pm25 < 30:
            corrected = 0.524*pm25 - 0.0862*rh + 5.75

        2) if 30 ≤ pm25 < 50:
            fraction = (pm25/20) - 1.5
            corrected = [0.786*fraction + 0.524*(1 - fraction)] * pm25
                        - (0.0862*rh)
                        + 5.75

        3) if 50 ≤ pm25 < 210:
            corrected = 0.786*pm25 - 0.0862*rh + 5.75

        4) if 210 ≤ pm25 < 260:
            fraction = (pm25/50) - 4.2
            corrected = [0.69*fraction + 0.786*(1 - fraction)] * pm25
                        - [0.0862*rh * (1 - fraction)]
                        + [2.966*fraction]
                        + [5.75*(1 - fraction)]
                        + [8.84e-4 * (pm25^2) * fraction]

        5) if pm25 ≥ 260:
            corrected = 2.966 + 0.69*pm25 + 8.84e-4*(pm25^2)

        Returns the corrected PM2.5 value, clamped to a minimum of 0.0.
        '''

        if pm25 < 30:
            corrected = D('0.524') * pm25 - D('0.0862') * rh + D('5.75')

        elif pm25 < 50:
            fraction = pm25 / D('20') - D('1.5')
            corrected = (
                (D('0.786') * fraction + D('0.524') * (D('1') - fraction)) * pm25
                - D('0.0862') * rh
                + D('5.75')
            )

        elif pm25 < 210:
            corrected = D('0.786') * pm25 - D('0.0862') * rh + D('5.75')

        elif pm25 < 260:
            fraction = pm25 / D('50') - D('4.2')
            corrected = (
                (D('0.69') * fraction + D('0.786') * (D('1') - fraction)) * pm25
                - D('0.0862') * rh * (D('1') - fraction)
                + D('2.966') * fraction
                + D('5.75') * (D('1') - fraction)
                + D('0.000884') * (pm25**2) * fraction
            )

        else:
            corrected = (
            D('2.966')
            + D('0.69') * pm25
            + D('0.000884') * (pm25**2)
        )

        return max(corrected, D('0.0'))


class Coloc_PM25_LinearRegression(BaseCalibration):
    entry_model = PM25
    requires = ['pm25']
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