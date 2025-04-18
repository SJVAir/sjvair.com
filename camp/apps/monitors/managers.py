from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from model_utils.managers import InheritanceManager, InheritanceQuerySet


class MonitorQuerySet(InheritanceQuerySet):
    def get_active(self):
        cutoff = timezone.now() - timedelta(seconds=self.model.LAST_ACTIVE_LIMIT)
        return self.filter(latest_entries__timestamp__gte=cutoff).distinct()

    def get_inactive(self):
        cutoff = timezone.now() - timedelta(seconds=self.model.LAST_ACTIVE_LIMIT)
        return self.filter(Q(latest__isnull=True) | Q(latest__timestamp__lt=cutoff))

    def get_active_multisensor(self):
        return self.get_active().exclude(default_sensor='').exclude(location='inside')
    
    def with_latest_entry(self, entry_model, calibration=''):
        from camp.apps.monitors.models import LatestEntry

        content_type = ContentType.objects.get_for_model(entry_model)

        subquery = (LatestEntry.objects
            .filter(
                monitor_id=OuterRef('pk'),
                content_type=content_type,
                calibration=calibration
            )
            .values('object_id')[:1]
        )

        latest_entries = LatestEntry.objects.filter(
            content_type_id=content_type.pk,
            calibration=calibration or '',
        )

        monitors = (self
            .annotate(latest_entry_id=Subquery(subquery))
            .exclude(latest_entry_id__isnull=True)
            .prefetch_related(
                Prefetch('latest_entries', queryset=latest_entries, to_attr='filtered_latest_entries')
            )
        )

        entries = entry_model.objects.filter(pk__in=[m.latest_entry_id for m in monitors])
        entry_map = {e.pk: e for e in entries}

        for monitor in monitors:
            monitor.latest_entry = entry_map.get(monitor.latest_entry_id)

        return monitors


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
    
    def with_filtered_latest_entries(self, *args, **kwargs):
        return self.get_queryset().with_filtered_latest_entries(*args, **kwargs)
