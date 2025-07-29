from django.contrib import admin
from django.contrib.gis.admin import OSMGeoAdmin
from .models import Region


@admin.register(Region)
class RegionAdmin(OSMGeoAdmin):
    list_display = ('name', 'type', 'external_id')
    list_filter = ('type',)
    search_fields = ('name', 'external_id')
