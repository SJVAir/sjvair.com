import pandas as pd

from django.db.models import Avg, Count
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel


class AlertEvaluator:
    CREATION_WINDOW = pd.Timedelta('30m')
    UPDATE_WINDOW = pd.Timedelta('60m')
    MINIMUM_DURATION = pd.Timedelta('60m')

    def __init__(self, monitor):
        self.monitor = monitor
        self.entry_types = monitor.alertable_entry_types

    def evaluate(self):
        for entry_model, lookup in self.entry_types.items():
            active_alert = Alert.objects.filter(
                monitor_id=self.monitor.pk,
                entry_type=entry_model.entry_type,
                end_time__isnull=True,
            ).first()

            if not self.monitor.is_active and not active_alert:
                # Inactive monitor with no active alerts – skip it.
                continue

            if active_alert:
                # There's an active alert, so check if we need
                # to update or end it.
                self.update_check(active_alert, entry_model, lookup)
            else:
                # No current alert, check to see if we need to
                # create one.
                self.creation_check(entry_model, lookup)

    def get_level(self, entry_model, lookup, window):
        interval_delta = pd.to_timedelta(self.monitor.EXPECTED_INTERVAL)

        if interval_delta >= window:
            return self.get_current_level(entry_model, lookup)
        return self.get_average_level(entry_model, lookup, window)

    def get_average_level(self, entry_model, lookup, window):
        '''
        Calculate the average value over a specified window and return the corresponding Level.

        Args:
            entry_model: The entry model to query (e.g., PM25).
            minutes: The averaging window in minutes (e.g., 30 or 60).

        Returns:
            A Level instance corresponding to the averaged value, or None if no data is available.
        '''

        start = timezone.now() - window
        queryset = entry_model.objects.filter(
            monitor_id=self.monitor.pk,
            timestamp__gte=start,
            **lookup
        )

        result = queryset.aggregate(avg=Avg('value'), count=Count('value'))
        if result['count'] == 0:
            return None
        return entry_model.Levels.get_level(result['avg'])

    def get_current_level(self, entry_model, lookup):
        '''
        Return the Level corresponding to the most recent entry, if within a valid time window.

        The window is determined based on the monitor's EXPECTED_INTERVAL. If the most recent entry
        is too old (more than 2x the expected interval), this returns None.

        Args:
            entry_model: The entry model to query (e.g., PM25).

        Returns:
            A Level instance corresponding to the most recent entry value, or None if no recent data is available.
        '''

        entry = (entry_model.objects
            .filter(monitor_id=self.monitor.pk, **lookup)
            .order_by('-timestamp')
            .first()
        )

        if not entry:
            return None
        return entry_model.Levels.get_level(entry.value)

    def creation_check(self, entry_model, lookup):
        level = self.get_level(entry_model, lookup, window=self.CREATION_WINDOW)
        if not level or level < AQLevel.scale.MODERATE:
            # Below moderate (good) so no alert needed.
            return

        alert = Alert.objects.create(
            monitor=self.monitor,
            entry_type=entry_model.entry_type,
            start_time=timezone.now(),
        )
        alert.create_update(level, timestamp=alert.start_time)
        return alert

    def update_check(self, alert, entry_model, lookup):
        """
        Update an active alert if the level has changed,
        or close it out if the level has dropped to GOOD.
        """
        level = self.get_level(entry_model, lookup, window=self.UPDATE_WINDOW)
        if level is None:
            return

        last_update = alert.updates.latest()
        now = timezone.now()

        # If the level has changed but still isn't good, make the update.
        if level != last_update.get_level() and level != AQLevel.scale.GOOD:
            alert.create_update(level)
            return

        # If the new level is GOOD and the alert has lived long enough, we can end the alert.
        if level == AQLevel.scale.GOOD and (now - alert.start_time) >= self.MINIMUM_DURATION:
            alert.end_time = timezone.now()
            alert.save(update_fields=['end_time'])
            alert.create_update(level)
            return
