from django.contrib.admin.options import csrf_protect_m
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
    add_form = PurpleAirAddForm
    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'purple_id')
    list_display.insert(5, 'get_active_status')

    fields = MonitorAdmin.fields
    readonly_fields = ['location', 'position', 'county']

    add_fieldsets = (
        (None, {
            # 'classes': ('wide',),
            'fields': ('name', 'purple_id', 'thingspeak_key'),
        }),
    )

    def get_active_status(self, instance):
        return instance.is_active
    get_active_status.boolean = True
    get_active_status.short_description = 'Is active'

    def get_fieldsets(self, request, obj=None):
        if not obj:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        defaults = {}
        if obj is None:
            defaults['form'] = self.add_form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, obj, *args, **kwargs):
        super().save_model(request, obj, *args, **kwargs)
        print(import_monitor_data(obj.pk, {'results': 1}))
