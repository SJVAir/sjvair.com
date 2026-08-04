from abc import ABC, ABCMeta, abstractmethod

from django.utils.functional import cached_property

from camp.utils import classproperty


__all__ = ['BaseProcessor']


class ProcessorMeta(ABCMeta):
    def __str__(cls):
        return cls.name

    def __eq__(cls, other):
        if isinstance(other, str):
            return cls.name == other
        if isinstance(other, ProcessorMeta):
            return cls.name == other.name
        return False

    def __hash__(cls):
        return hash(str(cls))


class BaseProcessor(ABC, metaclass=ProcessorMeta):
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

    def __str__(self):
        return self.name

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
        Runs the processor and returns the resulting entry, or None if no
        value is produced.

        If a matching entry already exists (same monitor/timestamp/sensor/
        stage/processor), this behaves as an upsert: the existing entry's
        computed fields are updated in place to the freshly computed values
        when they differ, rather than just returning the stale row
        unchanged. This makes re-running the pipeline self-healing after a
        data correction or a calibration/algorithm change, not merely a
        resume mechanism — and the same (existing) row is returned either
        way, so process_entry_pipeline's recursion continues correctly
        downstream regardless of whether anything actually changed.
        '''
        if not self.is_valid():
            return

        processed = self.process()
        if processed is None:
            return

        if processed.validation_check():
            if commit:
                processed.save()
            return processed

        existing = processed.__class__.objects.filter(
            monitor_id=processed.monitor_id,
            timestamp=processed.timestamp,
            sensor=processed.sensor,
            stage=processed.stage,
            processor=processed.processor,
        ).first()

        if existing is None:
            # Rare race: validation_check() saw a conflict that's since gone.
            return None

        sync_fields = [*processed.declared_field_names, 'calibration_id']
        changed_fields = [
            field for field in sync_fields
            if getattr(existing, field) != getattr(processed, field)
        ]

        if changed_fields and commit:
            for field in changed_fields:
                setattr(existing, field, getattr(processed, field))
            existing.save()

        return existing
