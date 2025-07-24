import csv

from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin as gisadmin
from django.db.models import Count, F
from django.http import HttpResponse
from django.utils.safestring import mark_safe

from camp.apps.alerts.models import Alert
from camp.apps.archive.models import EntryArchive
from camp.apps.qaqc.admin import HealthCheckInline

from .forms import MonitorAdminForm, EntryExportForm
from .models import Group


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

    list_display = ['name', 'get_device', 'get_health_grade', 'county', 'get_active_status', 'is_sjvair', 'is_hidden', 'last_updated', 'get_subscriptions']
    list_editable = ['is_sjvair', 'is_hidden']
    list_filter = ['is_sjvair', 'is_hidden', 'device', MonitorIsActiveFilter, 'groups', 'location', 'county', HealthCheckFilter]

    fieldsets = [
        (None, {'fields': ['name', 'is_hidden', 'is_sjvair']}),
        ('Location Data', {'fields': ['county', 'location', 'position']}),
        ('Metadata', {'fields': ['groups', 'notes', 'data_provider', 'data_provider_url']}),
    ]

    csv_export_fields = ['id', 'name', 'get_device', 'health_grade', 'last_updated', 'county', 'is_sjvair', 'is_hidden', 'location', 'position', 'notes']
    search_fields = ['county', 'location', 'name']
    save_on_top = True

    change_form_template = 'admin/monitors/monitor/change_form.html'

    class Media:
        js = ['admin/js/collapse.js']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('health')
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
                alerts=self.get_alerts(object_id)
            )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def export_monitor_list_csv(self, request, queryset):
        fields = getattr(self, 'csv_export_fields', self.fields)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sjvair-monitor-list.csv"'
        writer = csv.DictWriter(response, fields, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        for monitor in queryset:
            row = {field: getattr(monitor, field) for field in fields}
            # Make sure the ID is quoted
            if 'id' in row:
                row['id'] = str(row['id'])
            writer.writerow(row)
        return response

    def get_alerts(self, object_id):
        return (Alert.objects
            .select_related('latest')
            .filter(
                monitor_id=object_id,
                end_time__isnull=True
            )
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


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'monitor_count')
    filter_horizontal = ('monitors',)

    def monitor_count(self, instance):
        return instance.monitors.count()
