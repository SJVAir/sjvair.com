import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from django.db import transaction
from django.db.models import Avg, Count, Max
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel, Level


@dataclass
class AlertResult:
    status: str  # 'ok' | 'insufficient' | 'no_data'
    window_start: datetime
    window_end: datetime
    value: Optional[float] = None
    level: Optional[Level] = None
    latest_timestamp: Optional[datetime] = None
    readings: int = 0
    required: int = 0
    previous: Optional['AlertResult'] = None  # always None on a previous result


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

    def get_results(self, now=None, previous=True):
        '''
        Return {entry_model: AlertResult} for every alertable entry type,
        all measured at one `now`, without touching alert records. Pass
        previous=False to skip the hour-before result (one query fewer per type).
        '''
        now = now or timezone.now()
        return {
            entry_model: self.get_result(entry_model, *self.split_config(config), now=now, previous=previous)
            for entry_model, config in self.entry_types.items()
        }

    def get_levels(self):
        '''
        Return {entry_model: Level or None} for every alertable entry type,
        without touching alert records.
        '''
        return {entry_model: result.level for entry_model, result in self.get_results(previous=False).items()}

    def evaluate(self, results=None):
        '''
        Bring this monitor's alert records in line with its trailing-hour
        levels, and return those levels. Pass `results` (from get_results) to
        reuse them. Alert records are bookkeeping only; subscriber texts are
        decided in notifications.py.
        '''
        if results is None:
            results = self.get_results(previous=False)
        levels = {entry_model: result.level for entry_model, result in results.items()}
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
        return self.compute(entry_model, lookup, interval, timezone.now()).level

    def get_result(self, entry_model, lookup, interval=None, now=None, previous=True):
        '''
        Full AlertResult for one entry type at `now`. With previous=True, also
        carries the result for the hour before its window.
        '''
        now = now or timezone.now()
        result = self.compute(entry_model, lookup, interval, now)
        if previous:
            result.previous = self.compute(entry_model, lookup, interval, now - self.WINDOW)
        return result

    def compute(self, entry_model, lookup, interval, now):
        '''One result (no previous) for the window ending at `now`.'''
        interval = pd.to_timedelta(interval or self.monitor.EXPECTED_INTERVAL)
        if interval >= self.WINDOW:
            # An hourly feed can't be averaged over an hour: use its latest reading.
            return self.latest_reading(entry_model, lookup, interval, now)
        return self.average(entry_model, lookup, interval, now)

    def average(self, entry_model, lookup, interval, now):
        start = now - self.WINDOW
        stats = (entry_model.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp__gte=start,
                timestamp__lte=now,
                **lookup
            )
            .aggregate(avg=Avg('value'), count=Count('value'), latest=Max('timestamp'))
        )

        required = max(1, math.ceil((self.WINDOW / interval) * self.MIN_COVERAGE))
        result = AlertResult(
            status='ok',
            window_start=start,
            window_end=now,
            latest_timestamp=stats['latest'],
            readings=stats['count'],
            required=required,
        )
        if stats['count'] == 0:
            result.status = 'no_data'
        elif stats['count'] < required:
            result.status = 'insufficient'
        else:
            result.value = stats['avg']
            result.level = entry_model.Levels.get_level(stats['avg'])
        return result

    def latest_reading(self, entry_model, lookup, interval, now):
        '''
        The most recent reading, if it is no older than twice the expected
        interval.
        '''
        start = now - interval * 2
        entry = (entry_model.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp__gte=start,
                timestamp__lte=now,
                **lookup
            )
            .order_by('-timestamp')
            .first()
        )
        result = AlertResult(
            status='insufficient',
            window_start=start,
            window_end=now,
            readings=0,
            required=1,
        )
        if entry:
            result.status = 'ok'
            result.value = entry.value
            result.level = entry_model.Levels.get_level(entry.value)
            result.latest_timestamp = entry.timestamp
            result.readings = 1
        return result

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
