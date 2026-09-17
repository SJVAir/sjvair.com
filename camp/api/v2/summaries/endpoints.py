import calendar as cal
from datetime import datetime, timedelta

from resticus import generics
from resticus.http import Http400

from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.utils.functional import cached_property

from camp.api.v2.monitors.filters import MonitorFilter
from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.utils.datetime import make_aware

from .filters import BulkMonitorSummaryFilter
from .forms import BulkMonitorSummaryForm
from .serializers import BulkMonitorSummaryGroupSerializer, MonitorSummarySerializer, RegionSummarySerializer


VALID_RESOLUTIONS = {c.value for c in BaseSummary.Resolution}


class SummaryMixin:
    paginate = True
    page_size = 168  # one week of hourly data

    @cached_property
    def resolution(self):
        value = self.kwargs['resolution']
        if value not in VALID_RESOLUTIONS:
            raise Http404(f'"{value}" is not a valid resolution')
        return value

    @cached_property
    def entry_model(self):
        model = get_entry_model_by_name(self.kwargs['entry_type'])
        if model is None:
            raise Http404(f'"{self.kwargs["entry_type"]}" is not a valid entry type')
        return model

    def get_date_filter(self):
        """
        Build timestamp range filter from optional year/month/day URL kwargs.

        Uses explicit gte/lt range filters against LA-midnight boundaries rather
        than Django's __year/__month/__day lookups (which operate on the stored
        UTC value and misalign with the LA-localized timestamps the API returns).
        """
        year = self.kwargs.get('year')
        if year is None:
            return {}

        year = int(year)
        month = int(self.kwargs['month']) if self.kwargs.get('month') is not None else None
        day = int(self.kwargs['day']) if self.kwargs.get('day') is not None else None
        tz = settings.DEFAULT_TIMEZONE

        if day is not None:
            start = make_aware(datetime(year, month, day), tz)
            end = start + timedelta(days=1)
        elif month is not None:
            _, days_in_month = cal.monthrange(year, month)
            start = make_aware(datetime(year, month, 1), tz)
            end = start + timedelta(days=days_in_month)
        else:
            start = make_aware(datetime(year, 1, 1), tz)
            end = make_aware(datetime(year + 1, 1, 1), tz)

        return {'timestamp__gte': start, 'timestamp__lt': end}

    def get_queryset(self):
        # super() here → generics.ListEndpoint.get_queryset() → self.model.objects.all()
        return super().get_queryset().filter(
            resolution=self.resolution,
            entry_type=self.entry_model.entry_type,
            **self.get_date_filter(),
        ).order_by('timestamp')


class MonitorSummaryList(SummaryMixin, generics.ListEndpoint):
    model = MonitorSummary
    serializer_class = MonitorSummarySerializer

    def get_queryset(self):
        monitor = getattr(self.request, 'monitor', None)
        if monitor is None:
            raise Http404('Monitor not found')
        processor = self.request.GET.get('processor', '')
        # super() → SummaryMixin.get_queryset() → ListEndpoint → MonitorSummary.objects.all()
        # SummaryMixin applies resolution/entry_type/date filters
        # We add monitor/processor on top
        return super().get_queryset().filter(monitor=monitor, processor=processor)


class BulkMonitorSummaryList(SummaryMixin, generics.ListEndpoint):
    """Summary statistics for every published monitor matching an inclusive `start`/`end` date
    range, optionally scoped to one or more `region` ids (covered by any of their boundaries)
    or a `bbox` (`west,south,east,north`). Each result is a monitor (same shape as the other
    monitor endpoints) with its matching rows nested under `summaries`.

    `start` and `end` are required, and the span is capped per resolution (31 days for
    hourly, 366 days for daily); invalid parameters return a 400 with form errors.

    By default each monitor's published series is returned - the same calibration the map
    endpoints display for that monitor type (e.g. EPA-calibrated PM2.5 for PurpleAir, raw for
    reference monitors whose default processor isn't summarized). Pass `processor` to select
    one exact processor across all monitors instead (blank for raw).

    Pagination is by summary row, not by monitor, to keep response size bounded regardless
    of how many monitors or rows-per-monitor a request matches - rows are ordered by
    monitor id then timestamp, so a monitor with more rows than fit on one page is split
    across pages rather than truncated. To detect a split: if the last monitor `id` on a
    page matches the first monitor `id` on the next page, concatenate their `summaries`
    arrays - it's the same monitor continued, not a duplicate.
    """

    model = MonitorSummary
    serializer_class = BulkMonitorSummaryGroupSerializer
    form_class = BulkMonitorSummaryForm
    filter_class = BulkMonitorSummaryFilter

    @cached_property
    def form(self):
        return self.get_form(self.request.GET, resolution=self.resolution)

    def get(self, request, *args, **kwargs):
        if not self.form.is_valid():
            return Http400({'errors': self.form.errors.get_json_data()})
        return super().get(request, *args, **kwargs)

    def get_date_filter(self):
        tz = settings.DEFAULT_TIMEZONE
        start = make_aware(datetime.combine(self.form.cleaned_data['start'], datetime.min.time()), tz)
        end = make_aware(datetime.combine(self.form.cleaned_data['end_exclusive'], datetime.min.time()), tz)
        return {'timestamp__gte': start, 'timestamp__lt': end}

    def get_processor_filter(self):
        """
        Which summary series to return. An explicit `?processor=` (blank
        included) is an exact match across all monitors. Otherwise, per
        monitor type, use the DefaultCalibration the map publishes when it
        names a CALIBRATED processor (those are summarized), else raw -
        FEM cleaners produce CLEANED entries, which are never summarized.
        """
        if 'processor' in self.request.GET:
            return Q(processor=self.request.GET['processor'])

        lookup = Q()
        defaults = DefaultCalibration.objects.filter(entry_type=self.entry_model.entry_type)
        for default in defaults:
            if default.monitor_model is None:
                continue
            processor = ''
            for candidate in default.allowed_processors:
                if candidate.name == default.calibration and candidate.next_stage == self.entry_model.Stage.CALIBRATED:
                    processor = candidate.name
                    break
            lookup |= Q(**{f'monitor__{default.monitor_type}__isnull': False}, processor=processor)

        return lookup if lookup else Q(processor='')

    def get_queryset(self):
        monitors = (Monitor.objects.get_queryset()
            .get_public()
            .published_for(self.entry_model)
            .scope_to(
                region_ids=self.request.GET.getlist('region'),
                bbox=self.form.cleaned_data.get('bbox'),
            )
        )
        monitors = MonitorFilter(self.request.GET, queryset=monitors).qs

        # super() -> SummaryMixin.get_queryset() -> ListEndpoint -> MonitorSummary.objects.all()
        # SummaryMixin applies resolution/entry_type/date filters (get_date_filter() above).
        # Order by monitor_id, not `monitor`: the latter resolves to Monitor.Meta.ordering
        # (name), which is neither unique nor stable enough to paginate on.
        return (super()
            .get_queryset()
            .filter(self.get_processor_filter(), monitor__in=monitors)
            .order_by('monitor_id', 'timestamp')
        )

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        # `source` is this page's flat, monitor-ordered MonitorSummary rows.
        # Group them by monitor and attach as `summary_rows` (not `summaries` -
        # that name is claimed by the FK's reverse related manager) so
        # BulkMonitorSummaryGroupSerializer can nest them under each monitor.
        grouped = {}
        for row in source:
            grouped.setdefault(row.monitor_id, []).append(row)

        # Same related loads as MonitorMixin, so MonitorSerializer's health
        # and is_active lookups don't cost a query per monitor.
        monitors_by_id = (Monitor.objects
            .select_related('health')
            .with_last_entry_timestamp()
            .in_bulk(list(grouped))
        )
        monitors = []
        for monitor_id, rows in grouped.items():
            monitor = monitors_by_id.get(monitor_id)
            if monitor is None:
                continue
            monitor.summary_rows = rows
            monitors.append(monitor)

        return super().serialize(monitors, fields, include, exclude, fixup)


class RegionSummaryList(SummaryMixin, generics.ListEndpoint):
    model = RegionSummary
    serializer_class = RegionSummarySerializer

    def get_queryset(self):
        region_id = self.kwargs.get('region_id')
        try:
            region = Region.objects.get(sqid=region_id)
        except (Region.DoesNotExist, ValueError):
            raise Http404('Region not found')
        # super() → SummaryMixin.get_queryset() → ListEndpoint → RegionSummary.objects.all()
        return super().get_queryset().filter(region=region)
