import csv

from datetime import timedelta
from decimal import Decimal

from django import forms

from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin as gisadmin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Count, F, Max, Prefetch
from django.http import HttpResponse
from django.template.defaultfilters import floatformat
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.alerts.models import Alert
from camp.apps.archive.models import EntryArchive
from camp.apps.calibrations.admin import formula_help_text
from camp.apps.qaqc.models import SensorAnalysis
from camp.apps.qaqc.admin import SensorAnalysisInline
from camp.utils.forms import DateRangeForm

from .forms import MonitorAdminForm
from .models import Group, Calibration, Entry


def key_to_lookup(k):
    test_str = k * 2
    temp = len(test_str) // len(str(k))
    res = [k] * temp

    return tuple(res)


class HealthGradeListFilter(SimpleListFilter):
    title = "Health Grade"
    parameter_name = "grade"

    def lookups(self, request, model_admin): 
        return list(map(key_to_lookup, SensorAnalysis.health_grades.keys()))

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        try:
            (g_min, g_max) = SensorAnalysis.health_grades[self.value()]
            return queryset.filter(
                current_health__r2__gte=g_min,
                current_health__r2__lt=g_max,
            )
        except KeyError:
            return queryset


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
                cutoff = timezone.now() - timedelta(seconds=queryset.model.LAST_ACTIVE_LIMIT)
                lookup = {
                    'latest_id__isnull': False,
                    'latest__timestamp__gt': cutoff,
                }
                queryset = (queryset.filter if value else queryset.exclude)(**lookup)

            print(value, type(value))
            return queryset


class MonitorAdmin(gisadmin.OSMGeoAdmin):
    inlines = (SensorAnalysisInline,)
    actions = ['export_monitor_list_csv']
    form = MonitorAdminForm

    list_display = ['name', 'get_device', 'get_current_health', 'county', 'get_active_status', 'is_sjvair', 'is_hidden', 'last_updated', 'default_sensor', 'get_subscriptions']
    list_editable = ['is_sjvair', 'is_hidden']
    list_filter = ['is_sjvair', 'is_hidden', 'device', MonitorIsActiveFilter, 'groups', 'location', 'county', HealthGradeListFilter]

    fieldsets = [
        (None, {'fields': ['name', 'default_sensor', 'is_hidden', 'is_sjvair']}),
        ('Location Data', {'fields': ['county', 'location', 'position']}),
        ('Metadata', {'fields': ['groups', 'notes']}),
    ]

    csv_export_fields = ['id', 'name', 'get_device', 'health_grade', 'last_updated', 'county', 'default_sensor', 'is_sjvair', 'is_hidden', 'location', 'position', 'notes']
    search_fields = ['county', 'current_health__r2', 'location', 'name']
    save_on_top = True

    change_form_template = 'admin/monitors/monitor/change_form.html'
    change_list_template = 'admin/monitors/monitor/change_list.html'

    class Media:
        js = ['admin/js/collapse.js']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('current_health')
        queryset = queryset.prefetch_related(
            Prefetch('latest', queryset=Entry.objects.only('timestamp')),
        )
        queryset = queryset.annotate(
            last_updated=F('latest__timestamp'),
            subscription_count=Count('subscriptions'),
        )
        return queryset

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        extra_context.update(CALIBRATIONS=self.get_calibrations())
        return super().changelist_view(request, extra_context)

    @csrf_protect_m
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if extra_context is None:
            extra_context = {}
        if object_id is not None:
            extra_context.update(
                entry_archives=self.get_entry_archives(object_id),
                alert=self.get_alert(object_id)
            )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def export_monitor_list_csv(self, request, queryset):
        fields = getattr(self, 'csv_export_fields', self.fields)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sjvair-monitor-list.csv"'
        writer = csv.DictWriter(response, fields)
        writer.writeheader()
        for monitor in queryset:
            row = {field: getattr(monitor, field) for field in fields}
            writer.writerow(row)
        return response

    def get_alert(self, object_id):
        try:
            return Alert.objects.get(monitor_id=object_id, end_time__isnull=True)
        except Alert.DoesNotExist:
            return None

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

    def get_current_health(self, instance):
        if instance.current_health is None:
            return 'N/A'

        return render_to_string('admin/qaqc/letter_grade.html', {
            'analysis': instance.current_health,
        })
    get_current_health.short_description = 'Current Health'
    get_current_health.admin_order_field = 'current_health__r2'

    def get_entry_archives(self, object_id):
        queryset = EntryArchive.objects.filter(monitor_id=object_id)
        return queryset

    def get_calibrations(self):
        queryset = Calibration.objects.filter(monitor_type=self.model._meta.app_label)
        return {calibration.county: calibration.pm25_formula for calibration in queryset}

    def get_subscriptions(self, instance):
        return instance.subscription_count
    get_subscriptions.short_description = 'Subscriptions'
    get_subscriptions.admin_order_field = 'subscription_count'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'pm25_calibration_formula' in form.base_fields:
            form.base_fields['pm25_calibration_formula'].help_text = formula_help_text()

        sensor_choices = [(sensor, '-----' if sensor == '' else sensor) for sensor in self.model.SENSORS]

        sensor_required = False
        if obj is not None:
            sensor_required = not obj._meta.get_field('default_sensor').blank

        form.base_fields['default_sensor'] = forms.ChoiceField(choices=sensor_choices, required=sensor_required)

        return form

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
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


@admin.register(Calibration)
class CalibrationAdmin(admin.ModelAdmin):
    list_display = ('monitor_type', 'county', 'modified', 'get_pm25_formula')
    list_filter = ('monitor_type', 'county')

    def get_pm25_formula(self, instance):
        if instance.pm25_formula:
            return mark_safe(f'<code>{instance.pm25_formula}</code>')
        return '-'
    get_pm25_formula.short_description = 'PM2.5 Formula'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'pm25_formula' in form.base_fields:
            form.base_fields['pm25_formula'].help_text = formula_help_text()
        return form
