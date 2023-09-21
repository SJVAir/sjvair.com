from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.purpleair.models import PurpleAir


@admin.register(PurpleAir)
class PurpleAirAdmin(MonitorAdmin):
    csv_export_fields = MonitorAdmin.csv_export_fields[:]
    csv_export_fields.insert(2, 'purple_id')

    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'purple_id')
    list_display.insert(5, 'get_active_status')

    fields = MonitorAdmin.fields
    readonly_fields = ['location', 'position', 'county']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_active_status(self, instance):
        return instance.is_active
    get_active_status.boolean = True
    get_active_status.short_description = 'Is active'
