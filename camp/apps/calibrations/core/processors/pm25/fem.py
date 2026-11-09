from decimal import Decimal as D

from camp.apps.entries.models import PM25

from camp.apps.calibrations import processors
from ..base import BaseProcessor

__all__ = ['PM25_FEM_Cleaner']


@processors.register()
class PM25_FEM_Cleaner(BaseProcessor):
    entry_model = PM25
    required_stage = PM25.Stage.RAW
    next_stage = PM25.Stage.CLEANED

    MIN_VALID = -10
    MAX_VALID = 10000  # Instrument spec range; 99999 is the invalid sentinel

    def process(self):
        if self.entry.value is None:
            return None

        if (self.entry.value < self.MIN_VALID) or (self.entry.value > self.MAX_VALID):
            return None  # Discard clearly invalid data

        # Monitor types that track instrument alarms (e.g. BAM 1022) decide
        # whether this hour can be trusted. Others don't define the hook.
        is_disturbed = getattr(self.entry.monitor, 'is_disturbed', None)
        if is_disturbed is not None and is_disturbed(self.entry.timestamp):
            return None

        value = max(self.entry.value, 0)  # Clamp negative to 0
        return self.build_entry(value=value)
