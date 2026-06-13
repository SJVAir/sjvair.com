from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.vozbox.models import VOZBox


@admin.register(VOZBox)
class VOZBoxAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'sensor_id')

    search_fields = MonitorAdmin.search_fields[:]
    search_fields.append('sensor_id')
