from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.vozbox.models import VOZBox


@admin.register(VOZBox)
class VOZBoxAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'sensor_id')

    readonly_fields = MonitorAdmin.readonly_fields + ['sensor_id']

    fieldsets = [
        (None, {'fields': ['sensor_id', 'name', 'is_hidden', 'is_sjvair']}),
        ('Location Data', {'fields': ['host', 'county', 'location', 'get_map']}),
        ('Metadata', {'fields': ['groups', 'notes', 'data_provider', 'data_provider_url']}),
    ]

    search_fields = MonitorAdmin.search_fields[:]
    search_fields.append('sensor_id')

    def has_add_permission(self, request, obj=None):
        return False
