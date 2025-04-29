from decimal import Decimal as D

from camp.apps.entries.models import Temperature

from camp.apps.calibrations import processors
from .base import BaseProcessor

__all__ = ['AirGradientTemperature']


@processors.register()
class AirGradientTemperature(BaseProcessor):
    '''
    AirGradient Temperature Correction Equation
    https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    entry_model = Temperature
    required_stage = Temperature.Stage.RAW
    next_stage = Temperature.Stage.CALIBRATED

    def process(self):
        if self.entry.monitor.location == self.entry.monitor.LOCATION.inside:
            return

        value = self.get_correction(self.entry.celsius)
        if value is not None:
            return self.build_entry(value=value)

    def get_correction(self, celsius):
        if celsius < 10:
            return celsius * D('1.327') - D('6.738')
        return celsius * D('1.181') - D('5.113')
