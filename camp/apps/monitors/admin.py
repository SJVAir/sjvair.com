from decimal import Decimal

from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Max
from django.template import Template, Context
from django.template.defaultfilters import floatformat
from django.utils.dateparse import parse_datetime
from django.utils.safestring import mark_safe

from .models import Entry


class MonitorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'county', 'is_sjvair', 'is_hidden', 'last_updated', 'pm25_calibration_formula']
    list_editable = ['is_sjvair', 'is_hidden', 'pm25_calibration_formula']
    list_filter = ['is_sjvair', 'is_hidden', 'county']
    fields = ['name', 'county', 'is_hidden', 'is_sjvair', 'location', 'position', 'pm25_calibration_formula']

    change_form_template = 'admin/monitors/change_form.html'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'pm25_calibration_formula' in form.base_fields:
            form.base_fields['pm25_calibration_formula'].help_text = mark_safe(Template('''
                <p><a href="https://github.com/AxiaCore/py-expression-eval/#available-operators-constants-and-functions">Available operators, constants, and functions.</a></p>
                <p><b>Available variables:</b></p>
                <ul>
                    {% for env in environment %}<li>{{ env }}</li>{% endfor %}
                </ul>
            ''').render(Context({'environment': Entry.ENVIRONMENT})))
        return form

    def last_updated(self, instance):
        if instance.latest:
            return parse_datetime(instance.latest['timestamp'])
        return ''
