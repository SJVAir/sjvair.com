from abc import ABC, abstractmethod

from camp.utils import classproperty

class BaseEntryProcessor(ABC):
    '''
    Abstract base class for entry processing operations, such as cleaning or calibration.
    Subclasses should implement the `process()` method to return a new BaseEntry instance.
    '''

    entry_model = None

    def __init__(self, entry):
        if self.entry_model is not None:
            assert isinstance(entry, self.entry_model), (
                f"{self.__class__.__name__} expected {self.entry_model.__name__}, "
                f"got {entry.__class__.__name__}"
            )

        self.entry = entry

    @classproperty
    def name(cls):
        return cls.__name__

    @abstractmethod
    def process(self):
        '''
        Perform the processing step and return a new (unsaved) entry.
        Must be implemented by subclasses.
        '''
        pass

    def is_valid(self):
        '''
        Checks whether the processed entry is valid and worth saving.
        By default: ensures a non-null value.
        Subclasses may override this.
        '''
        return self.entry is not None and self.entry.value is not None
    
    def build_entry(self, **kwargs):
        '''
        Clones the current entry and applies additional fields.
        '''
        return self.entry.clone(**kwargs)

    def run(self, save=True):
        '''
        Runs the processor and returns the new entry, or None if no value is produced.
        '''
        if not self.is_valid():
            return None
        
        processed = self.process()
        if processed is not None and processed.validation_check():
            if save:
                processed.save()
            return processed
        return None
