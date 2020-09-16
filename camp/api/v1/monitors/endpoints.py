import uuid

from resticus import generics

from django.db.models import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from camp.utils.forms import DateRangeForm
from .filters import EntryFilter, MonitorFilter
from .forms import EntryForm
from .serializers import EntrySerializer, MonitorSerializer
from ..endpoints import CSVExport


class MonitorMixin:
    model = Monitor
    filter_class = MonitorFilter
    serializer_class = MonitorSerializer

    def get_object(self):
        return self.request.monitor


class MonitorList(MonitorMixin, generics.ListEndpoint):
    paginate = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(is_hidden=True)
        return queryset


class MonitorDetail(MonitorMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'


class EntryMixin:
    model = Entry
    filter_class = EntryFilter
    form_class = EntryForm
    serializer_class = EntrySerializer

    paginate = True
    page_size = 10080

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(monitor_id=self.request.monitor.pk)
        return queryset


class EntryList(EntryMixin, generics.ListCreateEndpoint):
    def serialize(self, source, **kwargs):
        if isinstance(source, QuerySet):
            fields = ['timestamp', 'sensor']
            if 'fields' in self.request.GET:
                for field in self.request.GET['fields'].split(','):
                    if field in EntrySerializer.value_fields:
                        fields.append(field)
            else:
                fields.extend(EntrySerializer.value_fields)
            return (entry for entry in source.values(*fields))
        return super().serialize(source, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.data = form.cleaned_data
        self.object.monitor_id = self.request.monitor.pk
        self.request.monitor.process_entry(self.object)
        self.object.save()
        return {"data": self.serialize(
            Entry.objects.get(pk=self.object.pk)
        )}


class EntryCSV(EntryMixin, CSVExport):
    form_class = DateRangeForm
    model = Entry
    filename = "SJVAir_{view.request.monitor.__class__.__name__}_{view.request.monitor.pk}_{data[start_date]}_{data[end_date]}.csv"
    columns = ['timestamp', 'sensor', 'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm100_env', 'pm10_env', 'pm25_env', 'pm100_standard', 'pm10_standard',
        'pm25_standard', 'pm25_avg_15', 'pm25_avg_60', 'pm25_aqi',
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
