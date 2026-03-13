from resticus import generics, http

from django.http import Http404
from django.utils.functional import cached_property

from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary

from .serializers import MonitorSummarySerializer, RegionSummarySerializer


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
        """Build timestamp filter kwargs from optional year/month/day URL kwargs."""
        year = self.kwargs.get('year')
        month = self.kwargs.get('month')
        day = self.kwargs.get('day')
        filters = {}
        if year:
            filters['timestamp__year'] = int(year)
        if month:
            filters['timestamp__month'] = int(month)
        if day:
            filters['timestamp__day'] = int(day)
        return filters

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


class RegionSummaryList(SummaryMixin, generics.ListEndpoint):
    model = RegionSummary
    serializer_class = RegionSummarySerializer

    def get_queryset(self):
        region_id = self.kwargs.get('region_id')
        try:
            region = Region.objects.get(pk=region_id)
        except (Region.DoesNotExist, ValueError):
            raise Http404('Region not found')
        # super() → SummaryMixin.get_queryset() → ListEndpoint → RegionSummary.objects.all()
        return super().get_queryset().filter(region=region)
