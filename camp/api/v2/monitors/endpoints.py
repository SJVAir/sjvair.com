from datetime import timedelta

from resticus import generics, http
from resticus.views import Endpoint

from django import forms
from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.core.cache import cache
from django.http import Http404
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.views.decorators.csrf import csrf_exempt

from camp.apps.entries.models import BaseEntry
from camp.apps.entries.tasks import data_export
from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.monitors.models import Monitor
from camp.utils.forms import LatLonForm
from camp.utils.views import CachedEndpointMixin

from .filters import MonitorFilter, get_entry_filterset
from .forms import EntryExportForm
from .serializers import EntrySerializer, MonitorSerializer
from ..endpoints import CSVExport, FormEndpoint


class MonitorMixin:
    model = Monitor
    serializer_class = MonitorSerializer

    def get_queryset(self):
        queryset = (super()
            .get_queryset()
            .select_related('health')
            .prefetch_related('latest_entries')
            .with_last_entry_timestamp()
        )

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


class MonitorList(CachedEndpointMixin, MonitorMixin, generics.ListEndpoint):
    cache_refresh = True
    cache_refresh_name = 'api:v2:monitors:monitor-list'
    cache_timeout = 90
    filter_class = MonitorFilter
    paginate = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(is_hidden=False)
        return queryset


class MonitorMetaEndpoint(Endpoint):
    def get_monitors(self):
        payload = {}

        monitor_subclasses = sorted(Monitor.get_subclasses(), key=lambda c: c.monitor_type)
        for monitor_model in monitor_subclasses:
            payload[monitor_model.monitor_type] = {
                'label': monitor_model._meta.verbose_name,
                'type': monitor_model.monitor_type,
                'expected_interval': getattr(monitor_model, 'EXPECTED_INTERVAL', None),
                'entries': {},
            }

            config_items = sorted(monitor_model.ENTRY_CONFIG.items(), key=lambda i: i[0].entry_type)
            for entry_model, config in config_items:
                payload[monitor_model.monitor_type]['entries'][entry_model.entry_type] = {
                    'sensors': config.get('sensors'),
                    'allowed_stages': config.get('allowed_stages', []),
                    'default_stage': monitor_model.get_default_stage(entry_model),
                    'default_calibration': monitor_model.get_default_calibration(entry_model),
                    'processors': {
                        stage: sorted([proc.name for proc in processors])
                        for stage, processors
                        in config.get('processors', {}).items()
                    }
                }
        return payload

    def get_entries(self):
        payload = {}
        for entry_model in BaseEntry.get_subclasses():
            payload[entry_model.entry_type] = {
                'label': entry_model.label,
                'type': entry_model.entry_type,
                'units': entry_model.units,
                'epa_aqs_code': entry_model.epa_aqs_code,
                'levels': entry_model.Levels.as_dict() if entry_model.Levels else None,
                'fields': ['timestamp', 'sensor', 'stage', 'processor'] + entry_model.declared_field_names,
            }
        return payload


    def get(self, request, *args, **kwargs):
        return {'data': {
            'monitors': self.get_monitors(),
            'entries': self.get_entries()
        }}


class MonitorDetail(CachedEndpointMixin, MonitorMixin, generics.DetailEndpoint):
    cache_timeout = 60
    cache_refresh = False

    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'
    serializer_class = MonitorSerializer

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('latest', lambda monitor: monitor.get_latest_data())]
        return super().serialize(source, fields, include, exclude, fixup)


class EntryExport(FormEndpoint):
    form_class = EntryExportForm
    login_required = True

    def get_email(self):
        if self.request.user.is_authenticated:
            return self.request.user.email or None
        return None

    def form_valid(self, form):
        email = self.get_email()
        task = data_export(self.request.monitor.pk, email=email, **form.cleaned_data)
        return http.JSONResponse({'task_id': str(task.id)}, status=202)


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
            .filter(is_hidden=False, location=Monitor.LOCATION.outside)
            .annotate(distance=Distance('position', form.point, spheroid=True))
            .order_by('distance')
            .with_latest_entry(self.entry_model)
        )

        return queryset[:3]

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        entry_type = self.entry_model.entry_type
        include = [
            ('distance', lambda monitor: monitor.distance.ft),
            ('latest', lambda monitor: EntrySerializer(getattr(monitor, f'latest_{entry_type}')).serialize()),
        ]
        return super().serialize(source, fields, include, exclude, fixup)


class CurrentData(CachedEndpointMixin, MonitorMixin, EntryTypeMixin, generics.ListEndpoint):
    cache_refresh = True
    cache_refresh_kwargs = [{'entry_type': E.entry_type} for E in BaseEntry.get_subclasses()]
    cache_refresh_name = 'api:v2:monitors:current-data'
    cache_timeout = 90

    paginate = False
    serializer_class = MonitorSerializer

    def get_queryset(self, *args, **kwargs):
        queryset = (super()
            .get_queryset(*args, **kwargs)
            .filter(
                is_hidden=False,
                position__isnull=False
            )
        )

        # Only monitors that are recently active...
        queryset = queryset.get_active(timedelta(
            days=settings.MONITOR_ACTIVE_WINDOW_DAYS
        ).total_seconds())

        # ...and recently healthy.
        queryset = queryset.filter_healthy(
            hours=settings.MONITOR_HEALTHY_WINDOW_HOURS,
            threshold=settings.MONITOR_HEALTHY_THRESHOLD,
        )

        queryset = queryset.with_latest_entry(self.entry_model)
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
