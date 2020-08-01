from resticus import generics

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from .filters import EntryFilter, MonitorFilter
from .serializers import EntrySerializer, MonitorSerializer
from ..endpoints import CSVExport


class EntryMixin:
    model = Entry
    filter_class = EntryFilter
    serializer_class = EntrySerializer

    paginate = True
    page_size = 10080

    @cached_property
    def monitor(self):
        try:
            return Monitor.objects.get(pk=self.kwargs['monitor_id'])
        except Monitor.DoesNotExist:
            raise Http404

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(monitor_id=self.monitor.pk)
        return queryset


class EntryList(EntryMixin, generics.ListEndpoint):
    def serialize(self, queryset, **kwargs):
        fields = ['timestamp', 'sensor']
        if 'fields' in self.request.GET:
            for field in self.request.GET['fields'].split(','):
                if field in EntrySerializer.value_fields:
                    fields.append(field)
        else:
            fields.extend(EntrySerializer.value_fields)
        return (entry for entry in queryset.values(*fields))


class EntryCSV(EntryMixin, CSVExport):
    model = Entry
    filename = "SJVAir_{view.monitor.__class__.__name__}_{view.monitor.pk}_{data[start_date]}_{data[end_date]}.csv"
    columns = ['timestamp', 'sensor', 'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm100_env', 'pm10_env', 'pm25_env', 'pm100_standard', 'pm10_standard',
        'pm25_standard', 'pm25_avg_15', 'pm25_avg_60', 'pm25_aqi', 'pm100_aqi',
        'particles_03um', 'particles_05um', 'particles_100um',
        'particles_10um', 'particles_25um', 'particles_50um',
    ]

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.values(*self.columns)
        return queryset

    def get_header_row(self):
        return self.columns

    def get_row(self, instance):
        return [instance[key] for key in self.columns]


class MonitorMixin:
    model = Monitor
    filter_class = MonitorFilter
    serializer_class = MonitorSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(is_hidden=True)
        return queryset


class MonitorList(MonitorMixin, generics.ListEndpoint):
    paginate = False


class MonitorDetail(MonitorMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'
