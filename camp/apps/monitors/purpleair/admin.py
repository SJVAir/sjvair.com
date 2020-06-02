from django.contrib import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.purpleair.forms import PurpleAirAddForm
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.tasks import import_monitor_data
from camp.utils.forms import DateRangeForm


@admin.register(PurpleAir)
class PurpleAirAdmin(admin.ModelAdmin):
    list_display = ['name', 'purple_id', 'last_updated', 'temperature', 'humidity', 'pm10', 'pm25', 'pm100']
    fields = ['name', 'purple_id', 'thingspeak_key']

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = PurpleAirAddForm
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        return (super()
            .get_queryset(request)
            .select_related('latest')
        )

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, obj, *args, **kwargs):
        super().save_model(request, obj, *args, **kwargs)
        print(import_monitor_data(obj.pk, {'results': 1}))

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
