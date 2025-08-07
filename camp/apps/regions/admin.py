from base64 import b64encode

import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.entries import models as entry_models
from camp.apps.entries.levels import _blend_hex
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
    list_display = ['name', 'type', 'external_id', 'current_version', 'monitor_count']
    list_filter = ['type', 'boundary__version']
    readonly_fields = ['name', 'slug', 'external_id', 'type', 'boundary', 'get_overview_map', 'get_monitor_map']
    search_fields = ['name', 'external_id']

    def get_fields(self, request, obj=None):
        return self.readonly_fields

    def get_queryset(self, *args, **kwargs):
        queryset = (super()
            .get_queryset(*args, **kwargs)
            .select_related('boundary')
            .with_monitor_count()
        )
        return queryset

    def monitor_count(self, instance):
        return instance.monitor_count
    monitor_count.short_description = 'Monitors'

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

    def get_overview_map(self, instance):
        if not instance or not instance.boundary:
            return 'n/a'

        try:
            if instance.type == Region.Type.COUNTY:
                county = instance.boundary
            else:
                county = Region.objects.get_county_region(instance).boundary

            width, height = {
                'landscape': (300, 200),
                'portrait': (200, 300),
            }[county.orientation]

            static_map = maps.StaticMap(
                width=width,
                height=height,
                buffer=0.1,
                # basemap=None,
            )

            if county.region_id != instance.pk:
                static_map.add(maps.Area(
                    geometry=county.geometry,
                    fill_color='white',
                    border_color='dimgrey',
                    alpha=.5,
                ))

            static_map.add(maps.Area(
                geometry=instance.boundary.geometry,
                fill_color='dodgerblue',
                border_color='royalblue',
                border_width=1,
                alpha=1,
            ))

            content = b64encode(static_map.render(format='png')).decode()
            return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.boundary.version} Map" />')
        except Exception:
            import traceback
            traceback.print_exc()
    get_overview_map.short_description = 'Overview'

    def get_monitor_map(self, instance):
        if not instance or not instance.boundary:
            return 'n/a'

        try:
            width, height = {
                'landscape': (600, 450),
                'portrait': (450, 600),
            }[instance.boundary.orientation]

            static_map = maps.StaticMap(
                width=width,
                height=height,
                buffer=0.1,
                # basemap=None,
            )
            static_map.add(maps.Area(
                geometry=instance.boundary.geometry,
                fill_color='dodgerblue',
                border_color='royalblue',
                border_width=1,
                # alpha=0.2
            ))

            monitor_list = sorted(
                instance.monitors.with_last_entry_timestamp().with_latest_entry(entry_models.PM25),
                key=lambda m: (m.grade, m.position),
                reverse=True
            )

            active = 0
            for monitor in monitor_list:
                if monitor.is_active:
                    active += 0
                # fill_color = monitor.latest_entry.level.color if monitor.is_active else 'darkgray'
                fill_color = monitor.latest_entry.Levels.get_color(
                    monitor.latest_entry.level.value
                ) if monitor.is_active else 'darkgray'
                border_color = _blend_hex(fill_color, '#000000', .2) if monitor.is_active else 'dimgray'
                static_map.add(maps.Marker(
                    geometry=monitor.position,
                    size=100 if monitor.is_active else 50,
                    fill_color=fill_color,
                    border_color=border_color,
                    shape='^' if monitor.is_regulatory else 'o' if monitor.is_sjvair else 's',
                    border_width=1,
                ))

            content = b64encode(static_map.render(format='png')).decode()
            return mark_safe(f'''
                <div>{len(monitor_list)} Monitors ({active} Active, {len(monitor_list) - active} Inactive)</div>
                <img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.boundary.version} Map" />
            ''')
        except Exception:
            import traceback
            traceback.print_exc()
    get_monitor_map.short_description = 'Monitors'
