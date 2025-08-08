from rangefilter.filters import NumericRangeFilterBuilder

from django.contrib.gis import admin

from .models import Tract



from base64 import b64encode

import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region, Boundary
from camp.utils import maps


#Filter for UI, set default as percentile bounds 0-100
CustomNumericRangeFilter = (
    NumericRangeFilterBuilder(
        default_start = 0,
        default_end = 100,
        )
    )

@admin.register(Tract)
class Ces4Admin(OSMGeoAdmin):
    
    list_display = [
        'tract','pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p', 'char_asthma', 'char_asthma_p', 
        ]
    readonly_fields = ('display_info_and_maps',)
    
    list_filter = [
        ('pollution_p', CustomNumericRangeFilter), ('pol_ozone_p', CustomNumericRangeFilter),
        ('pol_pm_p', CustomNumericRangeFilter), ('char_asthma_p', CustomNumericRangeFilter),
        ]
    ordering = ('-ci_score_p', )
    search_fields = ['tract']
    
    def display_info_and_maps(self, obj):
        boundaries = obj.boundary.all()
        if not boundaries:
            return "No boundaries."

        html = ""
        for b in boundaries:
            info_html = render_to_string('admin/regions/boundary-info.html', {
                'instance': b,
                'metadata': yaml.dump(b.metadata).strip()
            })
            map_html = self.render_map(b)

            html += f"""
            <div style="display: flex; align-items: flex-start; gap: 20px; margin-bottom: 2em;">
                <div style="flex-shrink: 0;">
                    {map_html}
                </div>
                <div style="flex-grow: 1;">
                    <h4>{b}</h4>
                    {info_html}
                </div>
            </div>
            """

        return mark_safe(html)

    display_info_and_maps.short_description = 'Boundary Info and Maps'

    def render_map(self, instance):
        if not instance or not instance.geometry:
            return '-'

        static_map = maps.StaticMap(
            width=600,
            height=400,
            buffer=0.3
        )
        static_map.add(maps.Area(
            geometry=instance.geometry,
            fill_color='dodgerblue',
            border_color='dodgerblue',
        ))
        content = b64encode(static_map.render(format='png')).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.version} Map" />')
    render_map.short_description = 'Map'
    
    
    def get_fieldsets(self, request, obj=None):
        all_fields = [f.name for f in self.model._meta.get_fields() if f.concrete and not f.many_to_many]
        fields = all_fields + ['display_info_and_maps',]
        return (
            ('Tract Info', {
                'fields': fields,
            }),
        )
    
    def get_readonly_fields(self, request, obj=None):
        return [
            f.name for f in self.model._meta.get_fields()
            ] + ['display_info_and_maps', ]
        

    def has_add_permission(self, request, obj=None):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    