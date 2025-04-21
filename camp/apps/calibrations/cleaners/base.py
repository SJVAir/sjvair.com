from abc import ABC, abstractmethod

from camp.utils import classproperty


class BaseCleaner(ABC):
    '''
    Abstract base class for entry cleaning.
    Subclass this to implement pollutant-specific cleaning logic.
    '''

    model_class = None  # Optional: restrict to a specific entry model class

    def __init__(self, entry):
        if self.model_class is not None:
            assert isinstance(entry, self.model_class), (
                f"{self.__class__.__name__} expected {self.model_class.__name__}, "
                f"got {entry.__class__.__name__}"
            )

        self.entry = entry

    @classproperty
    def name(cls):
        return cls.__name__

    @abstractmethod
    def clean(self):
        '''
        Apply cleaning logic to a raw entry.
        Must return a new entry instance with stage='clean' and origin=raw_entry,
        or None if the entry should be dropped (e.g. invalid/spike).
        '''
        pass

    def is_applicable(self):
        '''
        Optional hook to short-circuit cleaning. Default: applies to all 'raw' entries.
        '''
        return raw_entry.stage == 'raw'