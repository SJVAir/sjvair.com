from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    list_display = MonitorAdmin.list_display[:1] + ['get_organization'] + MonitorAdmin.list_display[1:]
    list_filter = MonitorAdmin.list_filter[:] + ['organization']

    def get_organization(self, instance):
        if not instance.organization:
            return '-'
        url = reverse('admin:aqlite_organization_change', args=[instance.organization.pk])
        return format_html('<a href="{}">{}</a>', url, instance.organization.name)
    get_organization.short_description = 'Organization'
    get_organization.admin_order_field = 'organization__name'
