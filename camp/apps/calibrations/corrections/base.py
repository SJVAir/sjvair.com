from abc import ABC, abstractmethod

from ..processor import BaseEntryProcessor


class BaseCalibration(BaseEntryProcessor):
    '''
    Base class for calibrating entry models.
    Subclasses must implement `apply()` and define `requires` and `model_class`.
    '''

    requires = []  # List of required fields from entry.entry_context

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = self.entry.entry_context()
    
    def is_valid(self) -> bool:
        '''
        Returns True if the entry can be properly calibrated.
        '''
        if super().is_valid():
            return self.entry.is_valid_value() and self.has_required_context()
        return False

    def has_required_context(self) -> bool:
        '''
        Returns True if all required fields are present and not None.
        '''
        return all(
            key in self.context and self.context[key] is not None
            for key in self.requires
        )
    
    def build_entry(self, **kwargs):
        defaults = {
            'stage': self.entry_model.Stage.CALIBRATED,
            'calibration': self.name,
        }
        defaults.update(**kwargs)
        return super().build_entry(**defaults)