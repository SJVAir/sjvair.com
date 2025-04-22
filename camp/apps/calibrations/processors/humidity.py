from decimal import Decimal as D

from camp.apps.entries.models import Humidity

from .base import BaseProcessor

__all__ = ['AirGradientHumidity']


class AirGradientHumidity(BaseProcessor):
    '''
        AirGradient Relative Humidity Correction Equation
        https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    entry_model = Humidity
    required_stage = Humidity.Stage.RAW
    next_stage = Humidity.Stage.CALIBRATED

    def process(self):
        value = self.get_correction(self.entry.value)
        if value is not None:
            return self.build_entry(value=value)
    
    def get_correction(self, rh):
        return min(rh * D('1.259') + D('7.34'), D('100'))
