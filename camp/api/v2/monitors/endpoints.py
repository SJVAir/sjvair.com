from resticus import generics, http

from django import forms
from django.contrib.gis.db.models.functions import Distance
from django.core.cache import cache
from django.http import Http404
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.views.decorators.csrf import csrf_exempt

from camp.apps.monitors.models import Monitor
from camp.apps.entries.utils import get_entry_model_by_name
from camp.utils.forms import LatLonForm
from camp.utils.views import get_view_cache_key

from .filters import MonitorFilter, get_entry_filterset
from .serializers import EntrySerializer, MonitorSerializer
from ..endpoints import CSVExport


class MonitorMixin:
    model = Monitor
    serializer_class = MonitorSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.prefetch_related('latest_entries')
        return queryset

    def get_object(self):
        return self.request.monitor


class EntryTypeMixin:
    @cached_property
    def entry_model(self):
        EntryModel = get_entry_model_by_name(self.kwargs['entry_type'])
        if EntryModel is None:
            raise Http404(f'"{self.kwargs["entry_type"]}" is not a valid entry type')
        return EntryModel


class EntryMixin(EntryTypeMixin):
    serializer_class = EntrySerializer
    
    def get_queryset(self):
        queryset = self.entry_model.objects.all()
        if hasattr(self.request, 'monitor'):
            queryset = queryset.filter(monitor_id=self.request.monitor.pk)
        return queryset

    def get_filter_class(self):
        return get_entry_filterset(self.entry_model)
    
    def filter_queryset(self, queryset):
        FilterClass = self.get_filter_class()
        if FilterClass is not None:
            filter = FilterClass(self.request.GET, queryset=queryset, monitor=self.request.monitor)
            return filter.qs
        return queryset


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


class MonitorDetail(MonitorMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'
    serializer_class = MonitorSerializer

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('latest', lambda monitor: monitor.get_latest_data())]
        return super().serialize(source, fields, include, exclude, fixup)


class ClosestMonitor(MonitorMixin, EntryTypeMixin, generics.ListEndpoint):
    form_class = LatLonForm
    serializer_class = MonitorSerializer

    def get_queryset(self):
        form = self.get_form(self.request.GET)
        if not form.is_valid:
            return self.model.objects.none()

        queryset = (super()
            .get_queryset()
            .get_active()
            .with_latest_entry(self.entry_model)
            .exclude(is_hidden=True, latest__isnull=True, location='inside')
            .annotate(distance=Distance('position', form.point, spheroid=True))
            .order_by('distance')
        )
        return queryset[:3]

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('distance', lambda monitor: monitor.distance.ft)]
        return super().serialize(source, fields, include, exclude, fixup)


class CurrentData(MonitorMixin, EntryTypeMixin, generics.ListEndpoint):
    serializer_class = MonitorSerializer

    def get_queryset(self, *args, **kwargs):
        queryset = (super()
            .get_queryset(*args, **kwargs)
            .exclude(is_hidden=True)
            .with_latest_entry(self.entry_model)
        )
        return queryset
    
    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('latest', lambda monitor: EntrySerializer(monitor.latest_entry).serialize())]
        return super().serialize(source, fields, include, exclude, fixup)
    

class CreateEntry(EntryMixin, generics.CreateEndpoint):
    form_class = forms.Form
    upload_not_allowed = 'Direct entry uploads are not allowed for this monitor.'

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        if not self.request.monitor.ENTRY_UPLOAD_ENABLED:
            return http.Http403(self.upload_not_allowed)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        created = self.request.monitor.handle_payload(self.request.data)

        results = []
        for entry in created:
            results.append(entry)
            results.extend(self.request.monitor.process_entry_pipeline(entry))

        # Legacy
        entry = self.request.monitor.create_entry_legacy(self.request.data)
        if entry:
            self.request.monitor.check_latest(entry)

            if self.request.monitor.latest_id == entry.pk:
                self.request.monitor.save()

        return {'data': self.serialize(results)}

    def serialize(self, *args, **kwargs):
        kwargs['include'] = kwargs.get('include', []) + ['label']
        return super().serialize(*args, **kwargs)


class EntryList(EntryMixin, generics.ListEndpoint):    
    paginate = True
    page_size = 10080

    # TODO: make this more extensible in resticus.
    def filter_queryset(self, queryset):
        FilterClass = self.get_filter_class()
        if FilterClass is not None:
            filter = FilterClass(self.request.GET, queryset=queryset, monitor=self.request.monitor)
            return filter.qs
        return queryset


class EntryCSV(EntryMixin, CSVExport):
    streaming = True

    @cached_property
    def columns(self):
        fields = ['timestamp', 'sensor', 'stage', 'processor']
        for field in self.entry_model.declared_fields:
            fields.append(field.name)
        return fields

    def get_filename(self):
        filename = '_'.join(filter(bool, [
            'SJVAir',
            self.request.monitor.__class__.__name__,
            self.entry_model.__name__,
            self.request.GET.get('sensor'),
            str(self.request.monitor.pk),
            'export'
        ]))
        return f'{filename}.csv'

    def get_header_row(self):
        return self.columns

    def get_row(self, instance):
        serialized = self.serialize(instance)
        return [serialized.get(key, '') for key in self.columns]
