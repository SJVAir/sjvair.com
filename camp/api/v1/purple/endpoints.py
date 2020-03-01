from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from resticus import generics

from .filters import PurpleAirFilter, EntryFilter
from ..endpoints import CSVExport
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


class EntryExport(CSVExport):
    model = Entry
    filename = "PurpleAir_{view.device.pk}_{data[start_date]}_{data[end_date]}.csv"
    columns = [
        ('id', lambda i: i.pk),
        ('device_id', lambda i: i.device_id),
        ('timestamp', lambda i: int(i.timestamp.timestamp())),
        ('date', lambda i: i.timestamp.date()),
        ('time', lambda i: i.timestamp.time()),
        ('celcius', lambda i: i.celcius),
        ('fahrenheit', lambda i: i.fahrenheit),
        ('humidity', lambda i: i.humidity),
        ('pressure', lambda i: i.pressure),
        ('pm25_standard (A)', lambda i: i.pm2_a.get('pm25_standard') if i.pm2_a else ''),
        ('pm10_env (A)', lambda i: i.pm2_a.get('pm10_env') if i.pm2_a else ''),
        ('pm25_env (A)', lambda i: i.pm2_a.get('pm25_env') if i.pm2_a else ''),
        ('pm100_env (A)', lambda i: i.pm2_a.get('pm100_env') if i.pm2_a else ''),
        ('pm25_standard (B)', lambda i: i.pm2_b.get('pm25_standard') if i.pm2_b else ''),
        ('pm10_env (B)', lambda i: i.pm2_b.get('pm10_env') if i.pm2_b else ''),
        ('pm25_env (B)', lambda i: i.pm2_b.get('pm25_env') if i.pm2_b else ''),
        ('pm100_env (B)', lambda i: i.pm2_b.get('pm100_env') if i.pm2_b else ''),
    ]

    @cached_property
    def device(self):
        return get_object_or_404(PurpleAir, pk=self.kwargs['purple_air_id'])

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.filter(device_id=self.device.pk)
        return queryset
