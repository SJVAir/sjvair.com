import hashlib
import uuid

from datetime import datetime

from resticus import generics, http

from django import forms
from django.contrib.gis.db.models.functions import Distance
from django.db.models import QuerySet
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from camp.utils.forms import LatLonForm
from camp.utils.views import CachedEndpointMixin
from camp.api.v2.monitors.serializers import EntrySerializer as V2EntrySerializer
from .filters import EntryFilter, MonitorFilter
from .serializers import EntrySerializer, MonitorSerializer
from ..endpoints import CSVExport


class MonitorMixin:
    model = Monitor
    serializer_class = MonitorSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.select_related('latest')
        return queryset

    def get_object(self):
        return self.request.monitor


class MonitorList(CachedEndpointMixin, MonitorMixin, generics.ListEndpoint):
    cache_refresh = True
    cache_refresh_name = 'api:v1:monitors:monitor-list'
    cache_timeout = 90

    filter_class = MonitorFilter
    paginate = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(is_hidden=False)
        queryset = queryset.exclude(airgradient__isnull=False)
        return queryset


class MonitorDetail(CachedEndpointMixin, MonitorMixin, generics.DetailEndpoint):
    cache_refresh = False
    cache_timeout = 60

    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'


class ClosestMonitor(MonitorMixin, generics.ListEndpoint):
    form_class = LatLonForm

    def get_queryset(self):
        form = self.get_form(self.request.GET)
        if not form.is_valid():
            return self.model.objects.none()

        queryset = super().get_queryset()
        queryset = (queryset
            .get_active()
            .exclude(is_hidden=True)
            .exclude(latest__isnull=True)
            .exclude(location='inside')
            .annotate(distance=Distance('position', form.point, spheroid=True))
            .order_by('distance')
        )

        return queryset[:3]

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('distance', lambda monitor: monitor.distance.ft)]
        return super().serialize(source, fields, include, exclude, fixup)


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
    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if self.request.monitor.default_sensor and 'sensor' not in self.request.GET:
            queryset = queryset.filter(sensor=self.request.monitor.default_sensor)
        return queryset

    def serialize(self, source, **kwargs):
        if isinstance(source, QuerySet):
            fields = EntrySerializer.base_fields[::]
            if 'fields' in self.request.GET:
                for field in self.request.GET['fields'].split(','):
                    if field in EntrySerializer.available_fields:
                        fields.append(field)
            else:
                fields.extend(EntrySerializer.value_fields)
            return [entry for entry in source.values(*fields)]
        return super().serialize(source, **kwargs)

    def post(self, request, *args, **kwargs):
        if not request.monitor.ENTRY_UPLOAD_ENABLED:
            return http.Http403('Direct entry uploads are not allowed for this monitor.')
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Same as v2's CreateEntry: uploads go into the entries app only. The
        # legacy Entry table no longer receives writes.
        created = self.request.monitor.handle_payload(self.request.data)

        results = []
        for entry in created:
            results.append(entry)
            results.extend(self.request.monitor.process_entry_pipeline(entry))

        if not results:
            return {'error': 'Invalid data.'}

        return {'data': V2EntrySerializer(results, include=['label']).serialize()}


class EntryCSV(EntryMixin, CSVExport):
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
        filename = '_'.join(filter(bool, [
            'SJVAir',
            self.request.monitor.__class__.__name__,
            self.request.monitor.slug,
            self.request.GET.get('sensor'),
            str(self.request.monitor.pk),
            'export'
        ]))
        return f'{filename}.csv'

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.values(*self.columns)
        return queryset

    def get_header_row(self):
        return self.columns

    def get_row(self, instance):
        return [instance[key] for key in self.columns]
