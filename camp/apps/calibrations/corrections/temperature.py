from decimal import Decimal as D

from camp.apps.entries.models import Temperature
from camp.apps.calibrations.corrections.base import BaseCalibration

__all__ = ['AirGradientTemperature']


class AirGradientTemperature(BaseCalibration):
    '''
    AirGradient Temperature Correction Equation
    https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    entry_model = Temperature
    requires = ['temperature_c']

    def process(self):
        if self.entry.monitor.location == self.entry.monitor.LOCATION.inside:
            return

        value = self.get_correction(self.context['temperature_c'])
        if value is not None:
            return self.build_entry(value=value)
    
    def get_correction(self, celsius):
        if celsius < 10:
            return celsius * D('1.327') - D('6.738')
        return celsius * D('1.181') - D('5.113')