class BaseCalibration:
    '''
    Base class for calibrating entry models.
    Subclasses must implement `apply()` and define `requires` and `model_class`.
    '''

    requires = []  # List of required fields from entry.entry_context
    model_class = None  # Optional: restrict to a specific entry model class

    def __init__(self, entry):
        if self.model_class is not None:
            assert isinstance(entry, self.model_class), (
                f"{self.__class__.__name__} expected {self.model_class.__name__}, "
                f"got {entry.__class__.__name__}"
            )

        self.entry = entry
        self.context = entry.entry_context()

    def run(self):
        '''
        Checks if calibration is valid for this entry, then runs it.
        Returns the calibrated entry or None if skipped.
        '''
        if not self.is_valid():
            return None
        return self.apply()

    def is_valid(self) -> bool:
        '''
        Returns True if all required fields are present and not None.
        '''
        return all(
            key in self.context and self.context[key] is not None
            for key in self.requires
        )

    def prepare_calibrated_entry(self, **kwargs):
        '''
        Clones the entry and sets calibration.
        '''
        calibrated = self.entry.clone()
        calibrated.calibration = self.__class__.__name__
        for attr, value in kwargs.items():
            setattr(calibrated, attr, value)
        return calibrated

    def apply(self):
        '''
        Override this method to implement the calibration logic.
        Must return the new calibrated entry (or None if skipped).
        '''
        raise NotImplementedError("Subclasses must implement `.apply()`")
