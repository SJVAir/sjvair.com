from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Max
from django.template import Template, Context
from django.template.defaultfilters import floatformat
from django.utils.safestring import mark_safe

from .models import Entry


class MonitorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'is_sjvair', 'is_hidden', 'last_updated', 'temperature', 'humidity',
        'pm10', 'pm25', 'pm100', 'get_pm25_calibration_formula']
    fields = ['name', 'is_hidden', 'is_sjvair', 'location', 'position', 'pm25_calibration_formula']

    def get_queryset(self, request):
        return (super()
            .get_queryset(request)
            .select_related('latest')
        )

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

    def get_pm25_calibration_formula(self, instance):
        return mark_safe(f'<code>{instance.pm25_calibration_formula}</code>')
    get_pm25_calibration_formula.short_description = 'PM2.5 Calibration Formula'

    def last_updated(self, instance):
        if instance.latest:
            return instance.latest.timestamp
        return ''

    def temperature(self, instance):
        if instance.latest is None:
            return ''

        temps = []
        if instance.latest.fahrenheit:
            temps.append(f'{intcomma(floatformat(instance.latest.fahrenheit, 1))}°F')
        if instance.latest.celcius:
            temps.append(f'{intcomma(floatformat(instance.latest.celcius, 1))}°C')
        return ' / '.join(temps)

    def humidity(self, instance):
        if instance.latest and instance.latest.humidity:
            return f'{int(round(instance.latest.humidity))}%'
        return ''

    def pm10(self, instance):
        if instance.latest:
            return instance.latest.pm10_env or ''
        return ''
    pm10.short_description = 'PM1.0'

    def pm25(self, instance):
        if instance.latest:
            return instance.latest.pm25_env or ''
        return ''
    pm25.short_description = 'PM2.5'

    def pm100(self, instance):
        if instance.latest:
            return instance.latest.pm100_env or ''
        return ''
    pm100.short_description = 'PM10.0'
