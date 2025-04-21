from decimal import Decimal as D

from camp.apps.entries.models import Humidity
from camp.apps.calibrations.corrections.base import BaseCalibration

__all__ = ['AirGradientHumidity']


class AirGradientHumidity(BaseCalibration):
    '''
        AirGradient Relative Humidity Correction Equation
        https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    entry_model = Humidity
    requires = ['humidity']
            
    def process(self):
        value = self.get_correction(self.context['humidity'])
        if value is not None:
            return self.build_entry(value=value)
    
    def get_correction(self, rh):
        return min(rh * D('1.259') + D('7.34'), D('100'))