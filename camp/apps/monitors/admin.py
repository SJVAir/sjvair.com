import csv

from base64 import b64encode

from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.contrib.admin.options import csrf_protect_m
from django.db import models
from django.contrib.gis import admin as gisadmin
from django.db.models import Count, F
from django.http import HttpResponse
from django.utils.safestring import mark_safe

from camp.apps.alerts.models import Alert
from camp.apps.archive.models import EntryArchive
from camp.apps.qaqc.admin import HealthCheckInline
from camp.template_tags import admin_changelist_url
from camp.utils import maps

from .forms import MonitorAdminForm, EntryExportForm
from .models import Group, Host, LatestEntry, Monitor


class HealthCheckFilter(SimpleListFilter):
    title = 'Health Grade'
    parameter_name = 'score'

    def lookups(self, request, model_admin):
        return list(zip('210', 'ABF'))

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        value = self.value()
        if value is not None:
            return queryset.filter(health_checks__score=value)


class MonitorIsActiveFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = 'Is active'

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'is_active'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return [
            (1, 'Yes'),
            (0, 'No'),
        ]

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        value = self.value()
        if value is not None:
            try:
                value = bool(int(value))
            except Exception:
                messages.error(request, f'Invalid value for is_active: {value}')
            else:
                queryset = (queryset.get_active if value else queryset.get_inactive)()
            return queryset


class MonitorAdmin(gisadmin.OSMGeoAdmin):
    inlines = [HealthCheckInline]
    actions = ['export_monitor_list_csv']
    form = MonitorAdminForm

    list_display = ['name', 'get_device', 'get_health_grade', 'county', 'get_active_status', 'is_sjvair', 'is_hidden', 'last_updated', 'legacy_last_updated', 'get_subscriptions']
    list_editable = ['is_sjvair', 'is_hidden']
    list_filter = ['is_sjvair', 'is_hidden', 'device', MonitorIsActiveFilter, 'groups', 'location', 'county', HealthCheckFilter]

    autocomplete_fields = ['host']
    readonly_fields = ['get_map']
    fieldsets = [
        (None, {'fields': ['name', 'is_hidden', 'is_sjvair']}),
        ('Location Data', {'fields': ['host', 'county', 'location', 'get_map']}),
        ('Metadata', {'fields': ['groups', 'notes', 'data_provider', 'data_provider_url']}),
    ]

    csv_export_fields = ['id', 'name', 'get_device', 'health_grade', 'last_updated', 'legacy_last_updated', 'county', 'is_sjvair', 'is_hidden', 'location', 'position', 'notes']
    search_fields = ['county', 'location', 'name', 'host__name', 'host__address', 'host__notes']
    save_on_top = True

    change_form_template = 'admin/monitors/monitor/change_form.html'

    class Media:
        js = ['admin/js/collapse.js']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('health', 'latest')
        queryset = queryset.with_last_entry_timestamp()
        queryset = queryset.annotate(
            last_updated=F('last_entry_timestamp'),
            subscription_count=Count('subscriptions'),
        )
        return queryset

    @csrf_protect_m
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if extra_context is None:
            extra_context = {}
        if object_id is not None:
            extra_context.update(
                entry_archives=self.get_entry_archives(object_id),
                alerts=self.get_alerts(object_id),
                latest_entries=self.get_latest_entries(object_id),
            )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def export_monitor_list_csv(self, request, queryset):
        fields = getattr(self, 'csv_export_fields', self.fields)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sjvair-monitor-list.csv"'
        writer = csv.DictWriter(response, fields, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for monitor in queryset:
            row = {}
            for field in fields:
                if value := getattr(monitor, field, None):
                    row[field] = value() if callable(value) else value
                elif method := getattr(self, field, None):
                    row[field] = method(monitor)
            # Make sure the ID is quoted
            if 'id' in row:
                row['id'] = str(row['id'])
            writer.writerow(row)
        return response

    def get_map(self, instance):
        if not instance or not instance.position:
            return '-'

        image = maps.from_geometries(
            instance.position,
            marker_size=350,
            marker_shape='*',
            marker_fill_color='dodgerblue',
            marker_shadow=True,
            height=400,
            width=600,
            buffer=1500,
            format='png',
        )
        content = b64encode(image).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="Position" />')
    get_map.short_description = 'Map'

    def get_alerts(self, object_id):
        return (Alert.objects
            .select_related('latest')
            .filter(
                monitor_id=object_id,
                end_time__isnull=True
            )
        )

    def get_latest_entries(self, object_id):
        return (LatestEntry.objects
            .filter(monitor_id=object_id)
            .order_by('entry_type', 'stage', 'processor')
        )

    def get_entry_archives(self, object_id):
        queryset = EntryArchive.objects.filter(monitor_id=object_id)
        return queryset

    def get_device(self, instance):
        return instance.get_device()
    get_device.short_description = 'Device'

    def _render_partner(self, name, url=None):
        if url is not None:
            return f'<a href="{url}">{name}</a>'
        return name

    def get_data_source(self, instance):
        content = self._render_partner(**instance.data_source)
        return mark_safe(content)
    get_data_source.short_description = 'Data Source'

    def get_data_providers(self, instance):
        content = '<br />'.join([
            self._render_partner(**item)
            for item in instance.data_providers
        ])
        return mark_safe(content)
    get_data_providers.short_description = 'Data Providers'

    def get_active_status(self, instance):
        return instance.is_active
    get_active_status.boolean = True
    get_active_status.short_description = 'Is active'

    def get_health_grade(self, instance):
        if instance.health is None:
            return 'N/A'
        return instance.health.grade
    get_health_grade.short_description = 'Health'
    get_health_grade.admin_order_field = 'health__score'

    def get_subscriptions(self, instance):
        return instance.subscription_count
    get_subscriptions.short_description = 'Subscriptions'
    get_subscriptions.admin_order_field = 'subscription_count'

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': EntryExportForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def last_updated(self, instance):
        if hasattr(instance, 'last_updated'):
            return instance.last_updated
        return ''
    last_updated.admin_order_field = 'last_updated'

    def legacy_last_updated(self, instance):
        if instance.latest:
            return instance.latest.timestamp
        return ''
    legacy_last_updated.admin_order_field = 'latest__timestamp'
    legacy_last_updated.short_description = 'Last Updated (Legacy)'


class LCSMonitorAdmin(MonitorAdmin):
    csv_export_fields = MonitorAdmin.csv_export_fields[:]
    csv_export_fields.insert(2, 'sensor_id')
    csv_export_fields.insert(3, 'hardware_id')

    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'sensor_id')
    list_display.insert(2, 'get_hardware_id')

    readonly_fields = ['name', 'location', 'position', 'county', 'get_map']

    search_fields = MonitorAdmin.search_fields[:]
    search_fields.extend(['hardware_id', 'sensor_id'])

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_hardware_id(self, instance):
        url = admin_changelist_url(instance)
        link = f'<a href="{url}?hardware_id={instance.hardware_id}">{instance.hardware_id}</a>'
        return mark_safe(link)


@admin.register(Host)
class HostAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'monitor_count')
    search_fields = ('name', 'email', 'phone', 'address', 'notes')

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.annotate(monitor_count=Count('monitors'))
        return queryset

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == 'address':
            # We don't need a ton of lines for an address.
            kwargs['widget'] = admin.widgets.AdminTextareaWidget(attrs={'rows': 3})
        return super().formfield_for_dbfield(db_field, **kwargs)

    @csrf_protect_m
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if extra_context is None:
            extra_context = {}
        if object_id is not None:
            hosted_monitors = (Monitor.objects
                .filter(host_id=object_id)
                .with_last_entry_timestamp()
            )
            extra_context.update(hosted_monitors=hosted_monitors,)
        return super().changeform_view(request, object_id, form_url, extra_context)

    def monitor_count(self, instance):
        return instance.monitor_count


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'monitor_count')
    filter_horizontal = ('monitors',)

    def monitor_count(self, instance):
        return instance.monitors.count()
