import math

import pandas as pd

from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel


class AlertEvaluator:
    # Every level comes from the trailing hour (e.g. 3:10-4:10 at 4:10).
    WINDOW = pd.Timedelta('60m')
    MINIMUM_DURATION = pd.Timedelta('60m')
    # Share of the expected readings that must be in WINDOW before an
    # average counts, so one reading (or a mostly-offline hour) can't
    # decide the level.
    MIN_COVERAGE = 0.5

    def __init__(self, monitor):
        self.monitor = monitor
        self.entry_types = monitor.alertable_entry_types

    @staticmethod
    def split_config(config):
        '''
        Split an ENTRY_CONFIG 'alerts' dict into queryset lookup kwargs and the
        alert stage's expected interval (None = the monitor's EXPECTED_INTERVAL).
        '''
        lookup = {key: value for key, value in config.items() if key != 'expected_interval'}
        return lookup, config.get('expected_interval')

    def get_levels(self):
        '''
        Return {entry_model: Level or None} for every alertable entry type,
        without touching alert records.
        '''
        return {
            entry_model: self.get_level(entry_model, *self.split_config(config))
            for entry_model, config in self.entry_types.items()
        }

    def evaluate(self):
        '''
        Bring this monitor's alert records in line with its trailing-hour
        levels, and return those levels (see get_levels). Alert records are
        bookkeeping only; subscriber texts are decided in notifications.py.
        '''
        levels = self.get_levels()
        for entry_model, level in levels.items():
            with transaction.atomic():
                active_alert = (Alert.objects
                    .select_related('latest')
                    .select_for_update(of=('self',))
                    .filter(
                        monitor_id=self.monitor.pk,
                        entry_type=entry_model.entry_type,
                        end_time__isnull=True,
                    )
                    .first()
                )
                if active_alert is not None:
                    self.update_check(active_alert, level)
                elif self.monitor.is_active:
                    self.creation_check(entry_model, level)
        return levels

    def get_level(self, entry_model, lookup, interval=None):
        interval = pd.to_timedelta(interval or self.monitor.EXPECTED_INTERVAL)
        if interval >= self.WINDOW:
            # An hourly feed can't be averaged over an hour: use its latest reading.
            return self.get_current_level(entry_model, lookup, interval)
        return self.get_average_level(entry_model, lookup, interval)

    def get_average_level(self, entry_model, lookup, interval):
        now = timezone.now()
        result = (entry_model.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp__gte=now - self.WINDOW,
                timestamp__lte=now,
                **lookup
            )
            .aggregate(avg=Avg('value'), count=Count('value'))
        )

        required = max(1, math.ceil((self.WINDOW / interval) * self.MIN_COVERAGE))
        if result['count'] < required:
            return None
        return entry_model.Levels.get_level(result['avg'])

    def get_current_level(self, entry_model, lookup, interval):
        '''
        Level of the most recent reading, or None if it is older than twice
        the expected interval.
        '''
        now = timezone.now()
        entry = (entry_model.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp__gte=now - interval * 2,
                timestamp__lte=now,
                **lookup
            )
            .order_by('-timestamp')
            .first()
        )
        if not entry or now - entry.timestamp > interval * 2:
            return None
        return entry_model.Levels.get_level(entry.value)

    def creation_check(self, entry_model, level):
        if level is None or level < AQLevel.scale.MODERATE:
            return None

        now = timezone.now()
        alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=entry_model.entry_type,
            start_time=now,
        )
        alert.create_update(level, timestamp=now)
        return alert

    def update_check(self, alert, level):
        if level is None:
            return
        latest = alert.latest or alert.updates.latest()
        latest.alert = alert  # get_level() reads it; skip the re-fetch
        if level == latest.get_level():
            return

        now = timezone.now()
        if level == AQLevel.scale.GOOD:
            if now - alert.start_time < self.MINIMUM_DURATION:
                return
            alert.end_time = now
            alert.save(update_fields=['end_time'])
        alert.create_update(level, timestamp=now)
