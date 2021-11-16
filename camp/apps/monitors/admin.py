from decimal import Decimal

from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import F, Max
from django.template import Template, Context
from django.template.defaultfilters import floatformat
from django.utils.dateparse import parse_datetime
from django.utils.safestring import mark_safe

from camp.utils.forms import DateRangeForm

from .models import Calibration, Entry


def formula_help_text():
    return mark_safe(Template('''
        <p>&#128279; <a href="https://github.com/AxiaCore/py-expression-eval/#available-operators-constants-and-functions">Available operators, constants, and functions.</a></p>
        <p><b>Available variables:</b></p>
        <ul>
            {% for env in environment %}<li>{{ env }}</li>{% endfor %}
        </ul>
    ''').render(Context({'environment': Entry.ENVIRONMENT})))


class MonitorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'county', 'is_sjvair', 'is_hidden', 'last_updated']
    list_editable = ['is_sjvair', 'is_hidden']
    list_filter = ['is_sjvair', 'is_hidden', 'location', 'county']
    fields = ['name', 'county', 'is_hidden', 'is_sjvair', 'location', 'position', 'notes', 'pm25_calibration_formula']
    search_fields = ['name']

    change_form_template = 'admin/monitors/change_form.html'
    change_list_template = 'admin/monitors/change_list.html'

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(last_updated=F('latest__timestamp'))
        return queryset

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        extra_context.update(CALIBRATIONS=self.get_calibrations())
        return super().changelist_view(request, extra_context)

    def get_calibrations(self):
        queryset = Calibration.objects.filter(monitor_type=self.model._meta.app_label)
        return {calibration.county: calibration.pm25_formula for calibration in queryset}

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'pm25_calibration_formula' in form.base_fields:
            form.base_fields['pm25_calibration_formula'].help_text = formula_help_text()
        return form

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def last_updated(self, instance):
        if instance.last_updated:
            return parse_datetime(instance.last_updated)
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
