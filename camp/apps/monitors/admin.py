from decimal import Decimal

from django import forms
from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import F, Max, Prefetch
from django.template import Template, Context
from django.template.defaultfilters import floatformat
from django.utils.dateparse import parse_datetime
from django.utils.safestring import mark_safe

from camp.apps.alerts.models import Alert
from camp.apps.archive.models import EntryArchive
from camp.apps.calibrations.admin import formula_help_text
from camp.utils.forms import DateRangeForm

from .models import Calibration, Entry


class MonitorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'get_current_health', 'county', 'is_sjvair', 'is_hidden', 'last_updated', 'default_sensor']
    list_editable = ['is_sjvair', 'is_hidden']
    list_filter = ['is_sjvair', 'is_hidden', 'location', 'county']
    fields = ['name', 'county', 'default_sensor', 'is_hidden', 'is_sjvair', 'location', 'position', 'notes', 'pm25_calibration_formula']
    search_fields = ['county', 'location', 'name']

    change_form_template = 'admin/monitors/change_form.html'
    change_list_template = 'admin/monitors/change_list.html'

    class Media:
        js = ['admin/js/collapse.js']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            Prefetch('latest', queryset=Entry.objects.only('timestamp')),
        )
        queryset = queryset.annotate(last_updated=F('latest__timestamp'))
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

    def get_alert(self, object_id):
        try:
            return Alert.objects.get(monitor_id=object_id, end_time__isnull=True)
        except Alert.DoesNotExist:
            return None

    def get_current_health(self, instance):
        if instance.current_health is None:
            return ''

        return mark_safe(Template('''
            {% load static %}
            <span>{{ monitor.current_health }}</span>
            &#32;
            {% if monitor.current_health.is_under_threshold %}
                <img src="{% static 'admin/img/icon-alert.svg' %}" alt="Inctive">
            {% endif %}
        ''').render(Context({
            'monitor': instance,
        })))
    get_current_health.short_description = 'Current Health'

    def get_entry_archives(self, object_id):
        queryset = EntryArchive.objects.filter(monitor_id=object_id)
        return queryset

    def get_calibrations(self):
        queryset = Calibration.objects.filter(monitor_type=self.model._meta.app_label)
        return {calibration.county: calibration.pm25_formula for calibration in queryset}

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
