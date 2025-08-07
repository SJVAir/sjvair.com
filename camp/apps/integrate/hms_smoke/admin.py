from base64 import b64encode

from django.contrib.gis import admin
from django.contrib.gis.admin import OSMGeoAdmin
from django.utils.safestring import mark_safe

from .models import Smoke
from camp.utils import maps


@admin.register(Smoke)
class SmokeAdmin(OSMGeoAdmin):
    date_hierarchy = 'date'
    list_display = ['id', 'satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_filter = ['satellite', 'density', 'is_final', ]
    ordering = ('-date', )
    
    def get_fieldsets(self, request, obj=None):
        fields = [f.name for f in self.model._meta.get_fields() if f.name != 'geometry'] + ['get_map', 'get_day_map']
        return [(None, {'fields': fields})]
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def get_map(self, instance):
        if not instance or not instance.geometry:
            return '-'
        width, height = (600, 400)
        static_map = maps.StaticMap(
            width=width,
            height=height,
            buffer=0.3
        )
        color = {
            'light': 'yellow',
            'medium': 'darkorange', 
            'heavy': 'maroon'
        }[instance.density]
        
        static_map.add(maps.Area(
            geometry=instance.geometry,
            fill_color=color,
            border_color='black',
        ))
        content = b64encode(static_map.render(format='png')).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk} "Map" />')
    get_map.short_description = 'Smoke Map'
    
    def get_day_map(self, instance):
        if not instance or not instance.geometry:
            return '-'
        width, height = (1000, 600)
        date_smokes = self.model.objects.filter(date=instance.date)
        if len(date_smokes) <=1:
            return 'This is the only smoke for the day.'
        static_map = maps.StaticMap(
            width=width,
            height=height,
            buffer=0.3
        )
        for smoke in date_smokes:
            color = {
                'light': 'yellow',
                'medium': 'darkorange', 
                'heavy': 'maroon'
            }[smoke.density]
            static_map.add(maps.Area(
                geometry=smoke.geometry,
                fill_color=color,
                border_color='black',
            ))
        content = b64encode(static_map.render(format='png')).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.date} "All Plumes This Day" />')
    get_day_map.short_description = 'All Plumes This Day'
            