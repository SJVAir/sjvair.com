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

        entry_type = entry_model._meta.model_name
        field_id = f'latest_{entry_type}_id'

        subquery = (LatestEntry.objects
            .filter(
                monitor_id=OuterRef('pk'),
                entry_type=entry_type,
                calibration=calibration
            )
            .values('object_id')[:1]
        )

        monitors = (self
            .annotate(**{field_id: Subquery(subquery)})
            .exclude(**{f'{field_id}__isnull': True})
        )

        entries = entry_model.objects.filter(pk__in=[getattr(m, field_id) for m in monitors])
        entry_map = {e.pk: e for e in entries}

        for monitor in monitors:
            entry = entry_map.get(getattr(monitor, field_id))
            setattr(monitor, f'latest_{entry_type}', entry)
            monitor.latest_entry = entry

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
