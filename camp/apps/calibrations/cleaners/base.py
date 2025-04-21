from ..processor import BaseEntryProcessor


class BaseCleaner(BaseEntryProcessor):
    '''
    Abstract base class for entry cleaning.
    Subclass this to implement pollutant-specific cleaning logic.
    '''

    def is_valid(self):
        '''
        Optional hook to short-circuit cleaning. Default: applies to all 'raw' entries.
        '''
        if super().is_valid():
            return self.entry.stage == self.entry.monitor.get_initial_stage(self.entry_model)
        return False

    def build_entry(self, **kwargs):
        defaults = {'stage': self.entry_model.Stage.CLEANED}
        defaults.update(**kwargs)
        return super().build_entry(**defaults)