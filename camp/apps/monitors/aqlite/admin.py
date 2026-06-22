from django.contrib import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.aqlite.models import AQLite, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'key_short', 'is_enabled', 'created', 'modified')
    list_filter = ('is_enabled',)
    search_fields = ('name', 'url')
    readonly_fields = ('created', 'modified')
    ordering = ('name',)

    def key_short(self, obj):
        return obj.key[:8] + '...' if obj.key else ''
    key_short.short_description = 'Key'


@admin.register(AQLite)
class AQLiteAdmin(MonitorAdmin):
    list_filter = MonitorAdmin.list_filter[:] + ['organization']
