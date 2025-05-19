from abc import ABC, abstractmethod

from django.utils.functional import cached_property

from camp.utils import classproperty


__all__ = ['BaseProcessor']


class BaseProcessor(ABC):
    '''
    Abstract base class for entry processing operations, such as cleaning or calibration.
    Subclasses should implement the `process()` method to return a new BaseEntry instance.
    '''

    entry_model = None
    required_context = []
    required_stage = None
    next_stage = None

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

    @cached_property
    def context(self):
        return self.entry.entry_context()

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
        return (
            isinstance(self.entry, self.entry_model)
            and self.entry.value is not None
            and self.has_required_stage()
            and self.has_required_context()
        )

    def has_required_context(self) -> bool:
        '''
        Returns True if all required fields are present and not None.
        '''
        return all(
            key in self.context and self.context[key] is not None
            for key in self.required_context
        )

    def has_required_stage(self) -> bool:
        '''
        Return True if the entry is in the correct stage for this processor.
        '''
        if self.required_stage is None:
            return True
        return self.required_stage == self.entry.stage

    def build_entry(self, **kwargs):
        '''
        Clones the current entry and applies additional fields.
        '''
        defaults = {'processor': self.name}
        if self.next_stage:
            defaults['stage'] = self.next_stage
        defaults.update(**kwargs)
        return self.entry.clone(**defaults)

    def run(self, commit=True):
        '''
        Runs the processor and returns the new entry, or None if no value is produced.
        '''
        if not self.is_valid():
            return

        processed = self.process()
        if processed is not None and processed.validation_check():
            if commit:
                processed.save()
            return processed
