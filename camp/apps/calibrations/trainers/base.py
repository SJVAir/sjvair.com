from abc import ABC, abstractmethod

from django.utils import timezone

from camp.apps.calibrations.models import Calibration
from camp.utils import classproperty


class BaseTrainer(ABC):
    entry_model = None
    features = []
    target = ''

    def __init__(self, pair, end_date=None):
        self.pair = pair
        self.end_date = end_date or timezone.now()

    @classproperty
    def name(cls):
        return cls.__name__

    def get_feature_queryset(self, **kwargs):
        lookup = {'monitor_id': self.pair.colocated_id}
        lookup.update(kwargs)
        return self.entry_model.objects.filter(**lookup)

    def get_target_queryset(self, **kwargs):
        lookup = {'monitor_id': self.pair.reference_id}
        lookup.update(kwargs)
        return self.entry_model.objects.filter(**lookup)

    @abstractmethod
    def process(self):
        """
        Subclasses must implement. Should return the best regression result, or None.
        """
        pass

    def run(self):
        """
        Handles running the trainer and post-processing.
        """
        result = self.process()
        if result and self.is_valid(result):
            result.save()
            return result

    def is_valid(self, result):
        """
        Default validation: result must not be None.
        Subclasses can override for stricter validation (e.g., minimum R²).
        """
        return result is not None

    def build_calibration(self, **kwargs):
        defaults = {
            'pair_id': self.pair.pk,
            'entry_type': self.pair.entry_type,
            'trainer': self.name,
        }
        defaults.update(kwargs)
        return Calibration(**defaults)
