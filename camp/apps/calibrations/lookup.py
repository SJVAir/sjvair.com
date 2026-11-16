from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.gis.db.models.functions import Distance

from camp.apps.calibrations.models import Calibration

_active = ContextVar('calibration_lookup', default=None)


def active_lookup():
    return _active.get()


class ChunkCalibrationLookup:
    '''
    Opt-in replacement for `Calibration.objects.get_for_entry` during bulk
    reprocessing, where thousands of entries share a handful of
    (entry type, trainer, position) combinations. Candidates for each
    combination are loaded once, up to `until`, ordered exactly as
    `CalibrationQuerySet.closest` orders them (distance, then newest
    created); each entry then takes the first candidate that had ended by
    its timestamp. Entries after `until` fall back to the real query.
    '''
    def __init__(self, until):
        self.until = until
        self._candidates = {}

    def get_for_entry(self, entry, trainer):
        if entry.timestamp > self.until:
            return Calibration.objects.get_for_entry(entry, trainer)

        position = entry.position
        key = (entry.entry_type, trainer, position.x, position.y, position.srid)
        if key not in self._candidates:
            self._candidates[key] = self._load(entry.entry_type, trainer, position)

        for calibration in self._candidates[key]:
            if calibration.end_time <= entry.timestamp:
                return calibration

    def _load(self, entry_type, trainer, position):
        calibrations = list(Calibration.objects
            .filter(
                pair__is_enabled=True,
                entry_type=entry_type,
                end_time__lte=self.until,
                trainer=trainer,
            )
            .annotate(distance=Distance('pair__reference__position', position, spheroid=True))
        )
        # NULL distances sort last in the database ordering.
        calibrations.sort(key=lambda c: (c.distance is None, c.distance, -c.created.timestamp()))
        return calibrations

    @contextmanager
    def activate(self):
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)
