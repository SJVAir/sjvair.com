from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.purpleair.forms import PurpleAirAddForm
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.tasks import import_monitor_data
from camp.utils.forms import DateRangeForm


@admin.register(PurpleAir)
class PurpleAirAdmin(MonitorAdmin):
    # list_display = ['name', 'purple_id', 'last_updated', 'temperature', 'humidity', 'pm10', 'pm25', 'pm100']
    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'purple_id')

    # fields = ['name', 'purple_id', 'thingspeak_key', 'location', 'position']
    fields = MonitorAdmin.fields
    fields.insert(1, 'purple_id')
    fields.insert(2, 'thingspeak_key')

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = PurpleAirAddForm
        return super().get_form(request, obj, **kwargs)

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, obj, *args, **kwargs):
        super().save_model(request, obj, *args, **kwargs)
        print(import_monitor_data(obj.pk, {'results': 1}))
