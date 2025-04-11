from datetime import timedelta

from django.db import models
from django.db.models import Q, Prefetch
from django.utils import timezone

from model_utils.managers import InheritanceManager, InheritanceQuerySet


class MonitorQuerySet(InheritanceQuerySet):
    def get_active(self):
        cutoff = timezone.now() - timedelta(seconds=self.model.LAST_ACTIVE_LIMIT)
        return self.filter(latest__timestamp__gte=cutoff)

    def get_inactive(self):
        cutoff = timezone.now() - timedelta(seconds=self.model.LAST_ACTIVE_LIMIT)
        return self.filter(Q(latest__isnull=True) | Q(latest__timestamp__lt=cutoff))

    def get_active_multisensor(self):
        return self.get_active().exclude(default_sensor='').exclude(location='inside')
    
    def with_latest_entries(self, calibration=None):
        """
        Prefetches only the latest entries for the given calibration type.

        Args:
            calibration (str or None): If None, fetches uncalibrated entries only.
                                       If str, fetches entries with matching calibration.
        """
        from camp.apps.monitors.models import LatestEntry

        latest_qs = (LatestEntry.objects
            .select_related('content_type')
            .filter(calibration=calibration or '')
        )

        return self.prefetch_related(
            Prefetch('latest_entries', queryset=latest_qs)
        )


class MonitorManager(InheritanceManager):
    _queryset_class = MonitorQuerySet

    def get_queryset(self):
        return super().get_queryset().select_subclasses()

    def get_active(self):
        return self.get_queryset().get_active()

    def get_inactive(self):
        return self.get_queryset().get_inactive()

    def get_active_multisensor(self):
        return self.get_queryset().get_active_multisensor()
