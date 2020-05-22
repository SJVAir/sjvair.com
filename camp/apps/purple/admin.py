from decimal import Decimal

from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Count
from django.template.defaultfilters import floatformat

from .forms import PurpleAirAddForm
from .models import PurpleAir, Entry
from .tasks import import_device_data
from camp.utils.forms import DateRangeForm


@admin.register(PurpleAir)
class PurpleAirAdmin(admin.OSMGeoAdmin):
    list_display = ['label', 'purple_id', 'location', # 'entry_count',
        'updated_at', 'temperature', 'humidity', 'pm10', 'pm25', 'pm100']
    fields = ['label', 'purple_id', 'position', 'location']

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = PurpleAirAddForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return PurpleAirAddForm.base_fields.keys()
        return self.fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return self.fields

    def get_queryset(self, request):
        return (super()
            .get_queryset(request)
            .select_related('latest')
            # .annotate(Count('entries'))
        )

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, obj, *args, **kwargs):
        super().save_model(request, obj, *args, **kwargs)
        print(import_device_data(obj.pk, {'results': 1}))

    def updated_at(self, instance):
        if instance.latest:
            return instance.latest.timestamp
        return '-'

    def entry_count(self, instance):
        return intcomma(instance.entries__count)
    entry_count.short_description = '# Entries'

    def temperature(self, instance):
        temps = []
        if instance.latest and instance.latest.fahrenheit:
            temps.append(f'{intcomma(floatformat(instance.latest.fahrenheit, 1))}°F')
        if instance.latest and instance.latest.celcius:
            temps.append(f'{intcomma(floatformat(instance.latest.celcius, 1))}°C')
        if temps:
            return ' / '.join(temps)
        return '-'

    def humidity(self, instance):
        if instance.latest and instance.latest.humidity:
            return f'{int(round(instance.latest.humidity))}%'
        return '-'

    def avg_pm(self, instance, key):
        try:
            values = []
            if instance.latest.pm2_a and key in instance.latest.pm2_a:
                values.append(Decimal(instance.latest.pm2_a[key]))
            if instance.latest.pm2_b and key in instance.latest.pm2_b:
                values.append(Decimal(instance.latest.pm2_b[key]))
            return floatformat(sum(values) / len(values), 2)
        except (AttributeError, IndexError, KeyError):
            return '-'

    def pm10(self, instance):
        return self.avg_pm(instance, 'pm10_env')
    pm10.short_description = 'PM1.0'

    def pm25(self, instance):
        return self.avg_pm(instance, 'pm25_env')
    pm25.short_description = 'PM2.5'

    def pm100(self, instance):
        return self.avg_pm(instance, 'pm100_env')
    pm100.short_description = 'PM10.0'


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'device', 'timestamp', 'temperature', 'humidity']
    list_filter = ['timestamp', 'device']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('device')
        return queryset

    def temperature(self, instance):
        if instance.fahrenheit:
            return f'{int(round(instance.fahrenheit))}°'
        return '-'

    def humidity(self, instance):
        if instance.humidity:
            return f'{int(round(instance.humidity))}%'
        return '-'
