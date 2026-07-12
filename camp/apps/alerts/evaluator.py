import pandas as pd

from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from camp.apps.alerts.models import Alert
from camp.apps.entries.levels import AQLevel


class AlertEvaluator:
    ESCALATION_WINDOW = pd.Timedelta('15m')
    DEESCALATION_WINDOW = pd.Timedelta('60m')
    MINIMUM_DURATION = pd.Timedelta('60m')
    NOTIFICATION_COOLDOWN = pd.Timedelta('30m')
    SEVERITY_BYPASS_RANKS = 2

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
                # Lock the alert row for the duration of the check so
                # overlapping evaluate() runs for the same alert can't
                # both pass the cooldown check and each create a
                # duplicate update/notification.
                with transaction.atomic():
                    active_alert = Alert.objects.select_for_update().get(pk=active_alert.pk)
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
            window: The averaging window (e.g., ESCALATION_WINDOW or DEESCALATION_WINDOW).

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

        interval = pd.to_timedelta(self.monitor.EXPECTED_INTERVAL)
        if timezone.now() - entry.timestamp > interval * 2:
            return None

        return entry_model.Levels.get_level(entry.value)

    def creation_check(self, entry_model, lookup):
        level = self.get_level(entry_model, lookup, window=self.ESCALATION_WINDOW)
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
        Escalate quickly (15-minute average), de-escalate or close slowly
        (60-minute average). A minimum gap is enforced between consecutive
        notifications on the same alert, unless the level jumps by 2 or
        more ranks.
        """
        fast_level = self.get_level(entry_model, lookup, window=self.ESCALATION_WINDOW)
        slow_level = self.get_level(entry_model, lookup, window=self.DEESCALATION_WINDOW)

        last_update = alert.updates.latest()
        current_level = last_update.get_level()
        now = timezone.now()

        candidate = None
        if fast_level and fast_level > current_level:
            candidate = fast_level
        elif slow_level and slow_level < current_level:
            candidate = slow_level

        if candidate is None:
            return

        if candidate == AQLevel.scale.GOOD:
            # If the new level is GOOD and the alert has lived long enough, we can end the alert.
            if (now - alert.start_time) >= self.MINIMUM_DURATION:
                alert.end_time = now
                alert.save(update_fields=['end_time'])
                alert.create_update(candidate)
            return

        rank_jump = abs(candidate.rank - current_level.rank)
        time_since_last = now - last_update.timestamp
        if time_since_last < self.NOTIFICATION_COOLDOWN and rank_jump < self.SEVERITY_BYPASS_RANKS:
            # Still within the cooldown and not a big enough jump to bypass it.
            return

        alert.create_update(candidate)
