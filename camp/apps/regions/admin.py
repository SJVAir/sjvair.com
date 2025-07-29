from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from .models import Region


@admin.register(Region)
class RegionAdmin(OSMGeoAdmin):
    list_display = ('name', 'type', 'external_id')
    list_filter = ('type',)
    readonly_fields = ['name', 'slug', 'external_id', 'type', 'metadata']
    search_fields = ('name', 'external_id')

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        messages.add_message(request, messages.WARNING, "The next message is a lie:")
        pass
