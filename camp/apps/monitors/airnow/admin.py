from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.airnow.models import AirNow
from camp.utils.forms import DateRangeForm


@admin.register(AirNow)
class AirNowAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:-1]
    list_display.append('get_active_status')
    list_editable = []

    fields = MonitorAdmin.fields
    readonly_fields = ['name', 'location', 'position', 'county']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_active_status(self, instance):
        return instance.is_active
    get_active_status.boolean = True
    get_active_status.short_description = 'Is active'

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)
