from decimal import Decimal as D

from camp.apps.entries.models import Humidity
from camp.apps.calibrations.corrections.base import BaseCalibration

__all__ = ['AirGradientHumidity']


class AirGradientHumidity(BaseCalibration):
    '''
        AirGradient Relative Humidity Correction Equation
        https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    model_class = Humidity
    requires = ['humidity']
        
    def apply(self):
        if value := self.get_correction(self.context['humidity']):
            calibrated = self.prepare_calibrated_entry(value=value)
            calibrated.value = value
            calibrated.save()
            return calibrated
    
    def get_correction(self, rh):
        return min(rh * D('1.259') + D('7.34'), D('100'))