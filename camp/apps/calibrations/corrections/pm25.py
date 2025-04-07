from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.models import Calibrator

from camp.apps.entries.models import PM25
from camp.apps.calibrations.corrections.base import BaseCalibration

__all__ = ['EPAPM25', 'ColocLinearRegression']


class EPAPM25(BaseCalibration):
    '''
        EPA's October 2021 PurpleAir correction algorithm,
        as described in the Fire and Smoke Map documentation.

        https://document.airnow.gov/airnow-fire-and-smoke-map-questions-and-answers.pdf
    '''
    model_class = PM25

    def process_entry(self, entry):
        calibrated = self.prepare_calibrated_entry(entry)
        context = entry.pollutant_context()
        calibrated.value = self.epa_oct_2021_correction(pm25=context['pm25'], rh=context['humidity'])
        calibrated.save()
        return calibrated
    
    def epa_oct_2021_correction(self, pm25, rh):
        """
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
        """

        if pm25 < 30:
            # Region 1
            corrected = 0.524 * pm25 - 0.0862 * rh + 5.75

        elif pm25 < 50:
            # Region 2
            fraction = (pm25 / 20) - 1.5
            corrected = (
                (0.786 * fraction + 0.524 * (1 - fraction)) * pm25
                - 0.0862 * rh
                + 5.75
            )

        elif pm25 < 210:
            # Region 3
            corrected = 0.786 * pm25 - 0.0862 * rh + 5.75

        elif pm25 < 260:
            # Region 4
            fraction = (pm25 / 50) - 4.2
            corrected = (
                (0.69 * fraction + 0.786 * (1 - fraction)) * pm25
                - 0.0862 * rh * (1 - fraction)
                + 2.966 * fraction
                + 5.75 * (1 - fraction)
                + 8.84e-4 * (pm25**2) * fraction
            )

        else:
            # Region 5 (pm25 >= 260)
            corrected = (
                2.966
                + 0.69 * pm25
                + 8.84e-4 * (pm25**2)
            )

        return max(corrected, 0.0)


class ColocLinearRegression(BaseCalibration):
    model_class = PM25

    def process_entry(self, entry):
        calibrated = self.prepare_calibrated_entry(entry)
        calibrated.value = self.get_calibration_value(entry)
        calibrated.save()
        return calibrated

    def get_calibration_value(self, entry):
        formula = self.get_local_calibration_formula(entry)

        if formula:
            parser = ExpressionParser()
            expression = parser.parse(formula)
            context = entry.pollutant_context()
            return expression.evaluate(context)
    
    def get_calibration_context(self):
        return {
            field: float(getattr(self, field, None) or 0)
            for field in self.ENVIRONMENT
        }
    
    def get_calibration_formula(self, entry):
        calibrator = (Calibrator.objects
            .filter(is_enabled=True)
            .exclude(calibration__isnull=True)
            .select_related('calibration')
            .closest(entry.monitor.position)
        )

        if calibrator is not None:
            calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
            if calibration is not None:
                return calibration.formula