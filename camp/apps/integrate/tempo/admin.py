from base64 import b64encode
from math import pow
import geopandas as gpd

from django.contrib import admin
from django.contrib.gis.admin import OSMGeoAdmin
from django.utils.safestring import mark_safe

from .models import TempoGrid
from camp.utils import maps
from camp.utils.geodata import gdf_from_zip



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
    