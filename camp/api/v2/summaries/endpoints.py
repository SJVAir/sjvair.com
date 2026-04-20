import calendar as cal
from datetime import datetime, timedelta

from resticus import generics

from django.conf import settings
from django.http import Http404
from django.utils.functional import cached_property

from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.utils.datetime import make_aware

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
