from base64 import b64encode

import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region, Boundary
from camp.utils import maps


class BoundaryInline(admin.TabularInline):
    model = Boundary
    readonly_fields = ['get_map', 'get_info']
    extra = 0
    show_change_link = True

    def get_fields(self, request, obj=None):
        return self.readonly_fields

    def get_info(self, instance):
        content = render_to_string('admin/regions/boundary-info.html', {
            'instance': instance,
            'metadata': yaml.dump(instance.metadata).strip()
        })
        return mark_safe(content)
    get_info.short_description = 'Boundary Information'

    def get_map(self, instance):
        if not instance or not instance.geometry:
            return '-'

        width, height = {
            'landscape': (600, 400),
            'portrait': (400, 600),
        }[instance.orientation]

        static_map = maps.StaticMap(
            width=width,
            height=height,
            buffer=0.3
        )
        static_map.add(maps.Area(
            geometry=instance.geometry,
            fill_color='dodgerblue',
            border_color='royalblue',
        ))
        content = b64encode(static_map.render(format='png')).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.version} Map" />')
    get_map.short_description = 'Map'


@admin.register(Region)
class RegionAdmin(OSMGeoAdmin):
    inlines = [BoundaryInline]
    list_display = ['name', 'type', 'external_id', 'current_version']
    list_filter = ['type', 'boundary__version']
    readonly_fields = ['name', 'slug', 'external_id', 'type', 'boundary', 'get_county_map']
    search_fields = ['name', 'external_id']

    def get_fields(self, request, obj=None):
        return self.readonly_fields

    def current_version(self, instance):
        return instance.boundary.version if instance.boundary else '-'
    current_version.short_description = 'Version'

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        messages.add_message(request, messages.WARNING, "The next message is a lie:")
        pass

    def save_formset(self, request, form, formset, change):
        pass

    def get_county_map(self, instance):
        if not instance or not instance.boundary:
            return 'n/a'

        try:
            county = Region.objects.get_county_region(instance)
            width, height = {
                'landscape': (300, 200),
                'portrait': (200, 300),
            }[county.boundary.orientation]

            static_map = maps.StaticMap(
                width=width,
                height=height,
                buffer=0.1,
                # basemap=None,
            )
            static_map.add(maps.Area(
                geometry=county.boundary.geometry,
                fill_color='white',
                border_color='black',
                # label=f'{instance.name}\n{instance.get_type_display()} in\n{county.name}',
                # label_position='bottom',
                # label_outline=True,
                alpha=.85,
            ))
            static_map.add(maps.Area(
                geometry=instance.boundary.geometry,
                fill_color='dodgerblue',
                border_color='royalblue',
                border_width=1,
                alpha=1,
            ))
            # static_map.add(maps.Marker(
            #     geometry=instance.boundary.geometry.centroid,
            #     fill_color='yellow',
            #     border_color='yellow',
            #     outline_width=3,
            #     outline_color='orange',
            #     outline=True,
            #     shape='*',
            #     # alpha=1,
            # ))

            content = b64encode(static_map.render(format='png')).decode()
            return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.boundary.version} Map" />')
        except Exception:
            import traceback
            traceback.print_exc()
    get_county_map.short_description = 'Map'
