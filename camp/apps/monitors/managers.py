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

    def published_for(self, entry_model):
        """
        Monitors whose type publishes `entry_model` on the map endpoints
        (current/, at/, closest/). A monitor type publishes an entry type
        iff a calibrations.DefaultCalibration row exists for that pair --
        a blank `calibration` means "publish the default stage". No row
        means the data is still ingested and available via the monitor
        detail / entries endpoints, just not surfaced on the map.
        """
        from camp.apps.calibrations.models import DefaultCalibration

        published_types = set(DefaultCalibration.objects
            .filter(entry_type=entry_model.entry_type)
            .values_list('monitor_type', flat=True)
        )

        lookup = Q()
        for subclass in self.model.get_subclasses():
            if subclass.monitor_type in published_types:
                lookup |= Q(**{f'{subclass.monitor_type}__isnull': False})

        if not lookup:
            return self.none()
        return self.filter(lookup)

    def get_active(self, seconds=None):
        seconds = seconds or self.model.LAST_ACTIVE_LIMIT
        cutoff = timezone.now() - timedelta(seconds=seconds)
        return self.filter(latest_entries__timestamp__gte=cutoff).distinct()

    def get_inactive(self, seconds=None):
        seconds = seconds or self.model.LAST_ACTIVE_LIMIT
        cutoff = timezone.now() - timedelta(seconds=seconds)
        return self.filter(Q(latest_entries__isnull=True) | Q(latest__timestamp__lt=cutoff))

    def get_public(self):
        """Monitors visible to the public API: not hidden, and of an enabled type."""
        queryset = self.filter(is_hidden=False)

        enabled_subclasses = self.model.get_enabled_subclasses()
        if len(enabled_subclasses) < len(self.model.get_subclasses()):
            lookup = Q()
            for subclass in enabled_subclasses:
                lookup |= Q(**subclass.type_queryset_filter())
            queryset = queryset.filter(lookup) if enabled_subclasses else queryset.none()

        return queryset

    def get_for_health_checks(self, hour: Optional[datetime] = None):
        """
        Return a queryset of all monitors whose class supports health checks
        for the given entry model.
        """
        queryset = self.none()

        if self.model._meta.model_name == 'monitor':
            lookup = Q()
            for subclass in self.model.get_subclasses():
                if subclass.health_checks_enabled():
                    lookup |= Q(**subclass.health_check_queryset_filter())

            if lookup:
                queryset = self.filter(lookup)

        elif self.model.health_checks_enabled():
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

    def scope_to(self, region_ids=None, bbox=None):
        """
        Scope to monitors covered by any of the `region_ids` (sqids) and/or
        within `bbox` (west, south, east, north). Raises Http404 for an
        unknown region id. Shared by the map-style endpoints (at/, bulk
        summaries) that accept `?region=` and `?bbox=`.
        """
        from django.http import Http404
        from camp.apps.regions.models import Region

        queryset = self.filter(position__isnull=False)

        if region_ids:
            regions = []
            for region_id in region_ids:
                try:
                    regions.append(Region.objects.get(sqid=region_id))
                except Region.DoesNotExist:
                    raise Http404(f'"{region_id}" is not a valid region id')
            queryset = queryset.in_regions(regions)

        if bbox:
            queryset = queryset.in_bbox(*bbox)

        return queryset

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
        '''
        Evaluate the queryset, keep monitors with a latest entry of
        `entry_model`, and attach it as `latest_<entry_type>`.

        A monitor keeps one LatestEntry per processor (e.g. the cleaned and
        the calibrated PM2.5). Without `stage`/`processor`, each monitor gets
        its type's published one (Monitor.get_published_lookup), falling back
        to its default stage and then the newest, as monitor detail does.
        '''
        from camp.apps.monitors.models import LatestEntry

        entry_type = entry_model.entry_type
        field_id = f'latest_{entry_type}_id'

        if stage is None and processor is None:
            subquery = self._published_latest_entry(entry_model)
        else:
            lookup = {
                'monitor_id': OuterRef('pk'),
                'entry_type': entry_type,
            }
            if stage is not None:
                lookup['stage'] = stage
                if stage == entry_model.Stage.CALIBRATED:
                    lookup['processor'] = processor or ''
            else:
                lookup['stage'] = entry_model.Stage.CALIBRATED
                lookup['processor'] = processor or ''

            subquery = Subquery(LatestEntry.objects
                .filter(**lookup)
                .values('entry_id')[:1]
            )

        monitors = (self
            .annotate(**{field_id: subquery})
            .exclude(**{f'{field_id}__isnull': True})
        )

        entries = entry_model.objects.filter(pk__in=[getattr(m, field_id) for m in monitors])
        entry_map = {e.pk: e for e in entries}

        for monitor in monitors:
            entry = entry_map.get(getattr(monitor, field_id))
            setattr(monitor, f'latest_{entry_type}', entry)
            monitor.latest_entry = entry

        return monitors

    def _published_latest_entry(self, entry_model):
        '''
        Expression for the entry_id of each monitor's published LatestEntry
        of `entry_model`. Monitor types publish different processors, so on
        the base Monitor queryset it's a CASE over the types.
        '''
        from django_smalluuid.models import SmallUUIDField
        from camp.apps.calibrations.models import DefaultCalibration
        from camp.apps.monitors.models import LatestEntry, Monitor

        calibrations = dict(DefaultCalibration.objects
            .filter(entry_type=entry_model.entry_type)
            .values_list('monitor_type', 'calibration'))

        def ranked(monitor_class):
            lookup = monitor_class.get_published_lookup(
                entry_model, calibrations.get(monitor_class.monitor_type, ''))
            # Ranked as models.published_rank does.
            return Subquery(LatestEntry.objects
                .filter(monitor_id=OuterRef('pk'), entry_type=entry_model.entry_type)
                .annotate(published_rank=Case(
                    When(Q(**lookup), then=Value(0)),
                    When(stage=monitor_class.get_default_stage(entry_model), then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                ))
                .order_by('published_rank', '-timestamp')
                .values('entry_id')[:1]
            )

        if self.model is not Monitor:
            return ranked(self.model)

        return Case(
            *[When(**subclass.type_queryset_filter(), then=ranked(subclass))
              for subclass in Monitor.get_subclasses()
              if entry_model in subclass.ENTRY_CONFIG],
            default=Value(None),
            output_field=SmallUUIDField(),
        )

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

    def with_entry_as_of(self, entry_model, timestamp, seconds=None):
        '''
        Each monitor's newest published `entry_model` entry (see
        Monitor.get_published_lookup) in the window before `timestamp`,
        falling back to its default stage, as current/ does.
        '''
        from camp.apps.calibrations.models import DefaultCalibration

        entry_type = entry_model.entry_type
        calibrations = dict(DefaultCalibration.objects
            .filter(entry_type=entry_type)
            .values_list('monitor_type', 'calibration'))
        results = []

        for monitor in self:
            window_seconds = seconds if seconds is not None else monitor.LAST_ACTIVE_LIMIT
            cutoff = timestamp - timedelta(seconds=window_seconds)

            window = (entry_model.objects
                .filter(monitor_id=monitor.pk, timestamp__lte=timestamp, timestamp__gte=cutoff)
                .order_by('-timestamp')
            )
            published = monitor.get_published_lookup(entry_model, calibrations.get(monitor.monitor_type, ''))
            entry = window.filter(**published).first()
            default_stage = {'stage': monitor.get_default_stage(entry_model)}
            if entry is None and published != default_stage:
                entry = window.filter(**default_stage).first()

            if entry is not None:
                setattr(monitor, f'latest_{entry_type}', entry)
                monitor.latest_entry = entry
                results.append(monitor)

        return results


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
