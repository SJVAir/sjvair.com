import hashlib
import uuid

from datetime import datetime

from resticus import generics, http

from django import forms
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import GEOSGeometry, Point
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.db.models import QuerySet
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from camp.utils.forms import LatLonForm
from camp.utils.views import get_view_cache_key
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


class MonitorList(MonitorMixin, generics.ListEndpoint):
    filter_class = MonitorFilter
    paginate = False

    def get(self, request, *args, **kwargs):
        cache_key = get_view_cache_key(self)

        clear_cache = '_cc' in request.GET
        if clear_cache:
            cache.delete(cache_key)
        else:
            data = cache.get(cache_key)
            if data is not None:
                return data

        response = super().get(request, *args, **kwargs)

        # cache for 90 seconds, but we have a task to
        # refresh the cache every 60 seconds
        cache.set(cache_key, response, 90)
        return response

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(is_hidden=True)
        return queryset

    def get_cache_key(self):
        key = str(self.__class__)


class MonitorDetail(MonitorMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'


class ClosestMonitor(MonitorMixin, generics.ListEndpoint):
    form_class = LatLonForm

    def get_queryset(self):
        form = self.get_form(self.request.GET)
        if not form.is_valid:
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

    def form_valid(self, form):
        entry = self.request.monitor.create_entry_legacy(self.request.data)
        if entry:
            self.request.monitor.check_latest(entry)

            if self.request.monitor.latest_id == entry.pk:
                self.request.monitor.save()

            return {'data': self.serialize(entry)}

        return {'error': 'Invalid data.'}


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
