from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.cimis.models import CIMIS


@admin.register(CIMIS)
class CIMISAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.remove('get_health_grade')
    list_display.insert(1, 'station_number')

    search_fields = MonitorAdmin.search_fields + ['station_number']

    readonly_fields = ['get_monitor_id', 'name', 'location', 'position', 'county', 'station_number', 'get_map']
    fieldsets = [
        (None, {'fields': ['get_monitor_id', 'station_number', 'name', 'is_hidden', 'is_sjvair']}),
        ('Location Data', {'fields': ['host', 'county', 'location', 'get_map']}),
        ('Metadata', {'fields': ['groups', 'notes', 'data_provider', 'data_provider_url']}),
    ]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
