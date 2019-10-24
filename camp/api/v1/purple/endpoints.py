from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from resticus import generics

from .filters import PurpleAirFilter, EntryFilter
from camp.apps.purple.models import PurpleAir, Entry


class PurpleAirMixin():
    model = PurpleAir
    fields = [
        'id',
        'label',
        'purple_id',
        'position',
        'location',
        ('latest', {
            'fields': [
                'id',
                'timestamp',
                'celcius',
                'fahrenheit',
                'humidity',
                'pressure',
                'pm2_a',
                'pm2_b',
            ]
        })
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.select_related('latest')
        return queryset


class PurpleAirList(PurpleAirMixin, generics.ListEndpoint):
    # streaming = False
    filter_class = PurpleAirFilter
    paginate = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(latest__isnull=True)
        return queryset


class PurpleAirDetail(PurpleAirMixin, generics.DetailEndpoint):
    lookup_url_kwarg = 'purple_air_id'


class EntryList(generics.ListEndpoint):
    model = Entry
    filter_class = EntryFilter
    fields = ['id', 'timestamp', 'position', 'location', 'celcius',
        'fahrenheit', 'humidity', 'pressure', 'pm2_a', 'pm2_b']
    page_size = 1440 # 1 day(-ish) worth of data

    @cached_property
    def device(self):
        return get_object_or_404(PurpleAir, pk=self.kwargs['purple_air_id'])

    def get_queryset(self):
        return self.model.objects.filter(
            device_id=self.device.pk,
        ).order_by('-timestamp')
