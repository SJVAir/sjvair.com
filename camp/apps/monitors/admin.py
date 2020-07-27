from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Max
from django.template.defaultfilters import floatformat
from django.utils.safestring import mark_safe


class MonitorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'last_updated', 'temperature', 'humidity', 'pm10', 'pm25', 'pm100', 'get_pm25_calibration_formula']
    fields = ['name', 'is_hidden', 'location', 'position', 'pm25_calibration_formula']

    def get_queryset(self, request):
        return (super()
            .get_queryset(request)
            .select_related('latest')
        )

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
