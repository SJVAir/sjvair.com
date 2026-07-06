from datetime import datetime, timedelta
from typing import Optional

from django.db.models import (
    BooleanField, DateTimeField, IntegerField,
    ExpressionWrapper, F, Q,
    Case, Count, Exists, Value, When,
    OuterRef, Subquery,
)
from django.db.models.functions import Coalesce
from django.db.models.query import ModelIterable
from django.utils import timezone

from model_utils.managers import InheritanceManager, InheritanceQuerySet


class InheritanceIterable(ModelIterable):
    def __iter__(self):
        queryset = self.queryset
        base_iter = ModelIterable(queryset)

        if getattr(queryset, 'subclasses', False):
            extras = tuple(queryset.query.extra.keys())
            subclasses = sorted(queryset.subclasses, key=len, reverse=True)
            annotation_names = queryset.query.annotations.keys()

            for obj in base_iter:
                sub_obj = None
                for s in subclasses:
                    sub_obj = queryset._get_sub_obj_recurse(obj, s)
                    if sub_obj:
                        break
                if not sub_obj:
                    sub_obj = obj

                for k in annotation_names:
                    try:
                        setattr(sub_obj, k, getattr(obj, k))
                    except AttributeError:
                        pass  # annotation wasn't actually selected in the SQL

                for k in extras:
                    setattr(sub_obj, k, getattr(obj, k))

                yield sub_obj
        else:
            yield from base_iter


class MonitorQuerySet(InheritanceQuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._iterable_class = InheritanceIterable

    def get_active(self, seconds=None):
        seconds = seconds or self.model.LAST_ACTIVE_LIMIT
        cutoff = timezone.now() - timedelta(seconds=seconds)
        return self.filter(latest_entries__timestamp__gte=cutoff).distinct()

    def get_inactive(self, seconds=None):
        seconds = seconds or self.model.LAST_ACTIVE_LIMIT
        cutoff = timezone.now() - timedelta(seconds=seconds)
        return self.filter(Q(latest_entries__isnull=True) | Q(latest__timestamp__lt=cutoff))

    def get_for_health_checks(self, hour: Optional[datetime] = None):
        """
        Return a queryset of all monitors whose class supports health checks
        for the given entry model.
        """
        queryset = self.none()

        if self.model._meta.model_name == 'monitor':
            from camp.apps.entries.models import PM25
            lookup = Q()
            for subclass in self.model.get_subclasses():
                config = subclass.ENTRY_CONFIG.get(PM25, {})
                if len(config.get('sensors', [])) >= 2:
                    lookup |= Q(**subclass.health_check_queryset_filter())

            if lookup:
                queryset = self.filter(lookup)

        elif self.model.supports_health_checks():
            queryset = self.all()

        if hour:
            from camp.apps.entries.models import PM25
            entry_qs = PM25.objects.filter(
                monitor=OuterRef('pk'),
                timestamp__gte=hour,
                timestamp__lt=hour + timedelta(hours=1),
                stage=PM25.Stage.RAW,
            )
            queryset = (queryset
                .annotate(has_entries=Exists(entry_qs))
                .filter(has_entries=True)
            )

        return queryset

    def get_active_multisensor(self):
        return self.get_active().exclude(default_sensor='').exclude(location='inside')

    def in_regions(self, regions):
        boundaries = [r.boundary.geometry for r in regions if r.boundary_id]
        if not boundaries:
            return self.none()

        query = Q()
        for geometry in boundaries:
            query |= Q(position__coveredby=geometry)
        return self.filter(query)

    def in_bbox(self, west, south, east, north):
        from django.contrib.gis.geos import Polygon
        bbox = Polygon.from_bbox((west, south, east, north))
        return self.filter(position__within=bbox)

    def with_grade(self):
        from django.db.models import CharField
        from camp.apps.monitors.models import Monitor

        whens = []
        for subclass in Monitor.get_subclasses():
            grade = getattr(subclass, 'GRADE', None)
            if grade in {Monitor.Grade.FEM, Monitor.Grade.FRM} and not subclass._meta.abstract:
                whens.append(
                    When(**{f'{subclass._meta.model_name}__isnull': False}, then=Value(grade))
                )

        return self.annotate(
            grade=Case(*whens, default=Value(Monitor.Grade.LCS), output_field=CharField())
        )

    def with_last_entry_timestamp(self):
        from camp.apps.monitors.models import LatestEntry

        subquery = (LatestEntry.objects
            .filter(monitor=OuterRef('pk'))
            .order_by('-timestamp')  # just in case
            .values('timestamp')[:1]
        )

        return self.annotate(last_entry_timestamp=Subquery(subquery, output_field=DateTimeField()))

    def with_latest_entry(self, entry_model, stage=None, processor=None):
        from camp.apps.monitors.models import LatestEntry

        entry_type = entry_model.entry_type
        field_id = f'latest_{entry_type}_id'

        lookup = {
            'monitor_id': OuterRef('pk'),
            'entry_type': entry_type,
        }

        if stage is not None:
            lookup['stage'] = stage
            if stage == entry_model.Stage.CALIBRATED:
                lookup['processor'] = processor or ''
        elif processor is not None:
            lookup['stage'] = entry_model.Stage.CALIBRATED
            lookup['processor'] = processor or ''

        subquery = (LatestEntry.objects
            .filter(**lookup)
            .values('entry_id')[:1]
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

    def select_health(self, hours: int = 24, min_score: int = 1, threshold: float = 0.8, as_of: Optional[datetime] = None):
        from camp.apps.monitors.models import Monitor
        from camp.apps.qaqc.models import HealthCheck

        as_of = as_of or timezone.now()
        cutoff = as_of - timedelta(hours=hours)
        required_passing = int(hours * threshold)

        passing_count = (
            HealthCheck.objects
            .filter(
                monitor=OuterRef('pk'),
                hour__gte=cutoff,
                hour__lte=as_of,
                score__gte=min_score
            )
            .values('monitor')
            .annotate(count=Count('id'))
            .values('count')[:1]
        )

        whens = []
        for subclass in Monitor.get_subclasses():
            model_name = subclass._meta.model_name
            if getattr(subclass, 'GRADE', None) == Monitor.Grade.LCS:
                whens.append(
                    When(**{
                        f'{model_name}__isnull': False,
                        'passing_health_checks__gte': required_passing,
                    }, then=Value(True))
                )
            else:
                # FEM/FRM monitors
                whens.append(
                    When(**{
                        f'{model_name}__isnull': False
                    }, then=Value(True))
                )

        queryset = self.annotate(
            passing_health_checks=Coalesce(
                Subquery(passing_count, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
            is_healthy=Case(
                *whens,
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        return queryset

    def filter_healthy(self, hours: int = 24, min_score: int = 1, threshold: float = 0.8, as_of: Optional[datetime] = None):
        return self.select_health(
            hours=hours,
            min_score=min_score,
            threshold=threshold,
            as_of=as_of,
        ).filter(is_healthy=True)


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

    def get_for_health_checks(self, hour: Optional[datetime] = None):
        return self.get_queryset().get_for_health_checks(hour)

    def with_grade(self):
        return self.get_queryset().with_grade()

    def in_regions(self, regions):
        return self.get_queryset().in_regions(regions)

    def in_bbox(self, west, south, east, north):
        return self.get_queryset().in_bbox(west, south, east, north)
