from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.cimis.models import CIMIS


@admin.register(CIMIS)
class CIMISAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.remove('get_health_grade')

    fields = MonitorAdmin.fields
    readonly_fields = ['name', 'location', 'position', 'county', 'station_number', 'get_map']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
