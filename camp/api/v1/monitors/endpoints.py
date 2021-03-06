import uuid

from datetime import datetime

from resticus import generics, http

from django import forms
from django.db.models import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from camp.apps.monitors.methane.models import Methane
from camp.utils.forms import DateRangeForm
from .filters import EntryFilter, MonitorFilter
from .forms import EntryForm, MethaneDataForm
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
    form_class = forms.Form
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
            fields = EntrySerializer.base_fields[::]
            if 'fields' in self.request.GET:
                for field in self.request.GET['fields'].split(','):
                    if field in EntrySerializer.value_fields:
                        fields.append(field)
            else:
                fields.extend(EntrySerializer.value_fields)
            return (entry for entry in source.values(*fields))
        return super().serialize(source, **kwargs)

    def form_valid(self, form):
        entry = self.request.monitor.create_entry(payload=self.request.data)
        self.request.monitor.process_entry(entry)
        entry.save()

        entry = Entry.objects.get(pk=entry.pk)
        self.request.monitor.check_latest(entry)
        return {"data": self.serialize(entry)}


class EntryCSV(EntryMixin, CSVExport):
    headers = {
        'pm25_env': 'pm25_avg_2',
    }

    @cached_property
    def columns(self):
        fields = EntrySerializer.base_fields[::]
        if 'fields' in self.request.GET:
            for field in self.request.GET['fields'].split(','):
                if field in EntrySerializer.value_fields:
                    fields.append(field)
        else:
            fields.extend(EntrySerializer.value_fields)
        return fields

    def get_filename(self):
        filename = '_'.join([
            'SJVAir',
            self.request.monitor.__class__.__name__,
            str(self.request.monitor.pk),
            'export'
        ])
        return f'{filename}.csv'

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.values(*self.columns)
        return queryset

    def get_header_row(self):
        return [self.headers.get(name, name) for name in self.columns]

    def get_row(self, instance):
        return [instance[key] for key in self.columns]


class MethaneDataUpload(generics.GenericEndpoint):
    form_class = MethaneDataForm

    def get(self, request, methane_id):
        form = self.get_form(request.GET)
        if self.validate_form(form):
            return self.form_valid(form)
        return self.form_invalid(form)

    def validate_form(self, form):
        if form.is_valid():
            if self.kwargs['methane_id'] != form.cleaned_data['id']:
                raise Http404
            return True
        return False

    def get_monitor(self, methane_id):
        return Methane.objects.get_or_create(
            name=methane_id,
            defaults={
                'is_hidden': True,
                'is_sjvair': False,
                'location': Monitor.LOCATION.outside,
            })[0]

    def form_valid(self, form):
        monitor = self.get_monitor(form.cleaned_data['id'])

        entry = monitor.create_entry(payload=form.cleaned_data)
        monitor.process_entry(entry)
        entry.save()

        entry = Entry.objects.get(pk=entry.pk)
        monitor.check_latest(entry)
        return http.Http200('')

    def form_invalid(self, form):
        return http.Http400({'errors': form.errors})



