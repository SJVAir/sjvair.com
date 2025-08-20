from django.contrib import admin
from django.contrib.gis.admin import OSMGeoAdmin

from .models import TempoGrid


@admin.register(TempoGrid)
class O3totAdmin(OSMGeoAdmin):
    date_hierarchy = 'timestamp'
    list_filter  = ['pollutant', ]
    readonly_fields = ['id', 'timestamp','pollutant', ]
    list_display = ['id', 'pollutant', 'timestamp',  ]
    ordering = ('-timestamp', )
    
    def has_add_permission(self, request, obj = None):
        return False
    
    def has_delete_permission(self, request, obj = None):
        return False
    
    def has_change_permission(self, request, obj = None):
        return False
    