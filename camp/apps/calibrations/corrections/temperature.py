from decimal import Decimal as D

from camp.apps.entries.models import Temperature
from camp.apps.calibrations.corrections.base import BaseCalibration

__all__ = ['AirGradientTemperature']


class AirGradientTemperature(BaseCalibration):
    '''
    AirGradient Temperature Correction Equation
    https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    model_class = Temperature
    requires = ['temperature_c']

    def apply(self):
        if self.entry.monitor.location == self.entry.monitor.LOCATION.inside:
            return
        
        if value := self.get_correction(self.context['temperature_c']):
            if calibrated := self.prepare_calibrated_entry(value=value):
                calibrated.save()
                return calibrated
    
    def get_correction(self, celsius):
        if celsius < 10:
            return celsius * D('1.327') - D('6.738')
        return celsius * D('1.181') - D('5.113')