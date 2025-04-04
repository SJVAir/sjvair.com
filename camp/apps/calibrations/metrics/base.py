

class BaseCalibration:
    """
    Base class for calibrating pollutants.
    """

    def prepare_calibrated_entry(self, entry):
        assert isinstance(entry, self.model_class)
        calibrated = entry.clone()
        calibrated.calibration_type = self.__class__.__name__
        return calibrated

    def process_entry(self, entry):
        """
        Calibrate the data.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")