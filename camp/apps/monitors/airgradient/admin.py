from django.contrib.gis import admin

from camp.apps.monitors.admin import LCSMonitorAdmin
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
class AirGradientAdmin(LCSMonitorAdmin):
    list_filter = LCSMonitorAdmin.list_filter[:]
    list_filter.insert(1, 'place')
