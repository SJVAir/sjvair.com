from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.airgradient.models import AirGradient, Place


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'token_short', 'is_enabled', 'created', 'modified')
    list_filter = ('is_enabled',)
    search_fields = ('name', 'url', 'token')
    readonly_fields = ('created', 'modified')
    ordering = ('name',)

    def token_short(self, obj):
        return obj.token[:8] + '...' if obj.token else ''
    token_short.short_description = 'Token'


@admin.register(AirGradient)
class AirGradientAdmin(MonitorAdmin):
    csv_export_fields = MonitorAdmin.csv_export_fields[:]
    csv_export_fields.insert(2, 'sensor_id')

    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'sensor_id')

    list_filter = MonitorAdmin.list_filter[:]
    list_filter.insert(1, 'place')

    readonly_fields = ['name', 'location', 'position', 'county', 'get_map']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
