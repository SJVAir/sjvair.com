from camp.apps.entries.models import Temperature
from camp.apps.calibrations.metrics.base import BaseCalibration


class AGTemperatureCorrection(BaseCalibration):
    '''
        AirGradient Temperature Correction Equation
        https://www.airgradient.com/documentation/calibration-algorithms/
    '''

    model_class = Temperature

    def process_entry(self, entry):
        calibrated = self.prepare_calibrated_entry(entry)

        if entry.monitor.location == entry.monitor.LOCATION.inside:
            return
        
        calibrated.value = self.get_correction(entry.celcius)
        calibrated.save()
        return calibrated
    
    def get_correction(self, celcius):
        if celcius < 10:
            return celcius * 1.327 - 6.738
        return celcius * 1.181 - 5.113