from decimal import Decimal as D

from camp.apps.entries.models import PM25

from ..base import BaseProcessor

__all__ = ['PM25_FEM_Cleaner']


class PM25_FEM_Cleaner(BaseProcessor):
    entry_model = PM25
    required_stage = PM25.Stage.RAW
    next_stage = PM25.Stage.CLEANED

    def process(self):
        if self.entry.value is None:
            return None

        if self.entry.value < -10:
            return None  # Discard clearly invalid data

        value = max(self.entry.value, 0)  # Clamp negative to 0
        return self.build_entry(value=value)
