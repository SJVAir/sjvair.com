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
    
    def get_fieldsets(self, request, obj=None):
        fields = [f.name for f in self.model._meta.get_fields()] + ['get_map']
        return [(None, {'fields': fields})]
    
    def has_add_permission(self, request, obj = None):
        return False
    
    def has_delete_permission(self, request, obj = None):
        return False
    
    def has_change_permission(self, request, obj = None):
        return False
    
    def get_map(self, instance):
        if not instance:
            return '-'
        width, height = (600, 400)
        gdf = gpd.read_file(instance.file)
        
        static_map = maps.StaticMap(
            width=width, 
            height=height,
            buffer=0.3
        )
        keys = {
            'no2': [5*pow(10, 15), 1*pow(10,16)],
            'hcho': [2*pow(10, 15), 1.25*pow(10, 16)],
            'o3tot': [220, 350],
        }
        pollutant = instance.pollutant
        for x in range(len(gdf)):
            curr = gdf.iloc[x]
            if curr[f'{pollutant}_col'] < keys[pollutant][0]:
                color = 'green'
            if curr[f'{pollutant}_col'] > keys[pollutant][1]:
                color = 'maroon'
            else:
                color = 'yellow'
            
            static_map.add(maps.Area(
                geometry=curr.geometry,
                fill_color=color,
                border_color=color
            ))
            
        content = b64encode(static_map.render(format='png')).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.timestamp} "Pollutant File" />')
    get_map.short_description = 'Pollutant File'
            
            
        
    