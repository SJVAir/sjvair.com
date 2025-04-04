from camp.apps.entries.models import Humidity
from camp.apps.calibrations.metrics.base import BaseCalibration


class AGHumidityCorrection(BaseCalibration):
    '''
        AirGradient Relative Humidity Correction Equation
        https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    model_class = Humidity

    def process_entry(self, entry):
        calibrated = self.prepare_calibrated_entry(entry)
        calibrated.value = self.get_correction(entry.value)
        calibrated.save()
        return calibrated
    
    def get_correction(self, rh):
        return min(rh * 1.259 + 7.34, 100)