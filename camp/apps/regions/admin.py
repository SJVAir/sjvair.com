import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.entries import models as entry_models
from camp.apps.entries.levels import _blend_hex
from camp.apps.regions.models import Region, Boundary, Location
from camp.utils import leaflet
from camp.utils.admin import LeafletMapMixin, ReadOnlyAdminMixin


class CountyFilter(admin.SimpleListFilter):
    title = 'county'
    parameter_name = 'county'

    def lookups(self, request, model_admin):
        counties = (
            Region.objects
            .filter(type=Region.Type.COUNTY, boundary__isnull=False)
            .order_by('name')
        )
        return [(c.pk, c.name) for c in counties]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        try:
            county = (
                Region.objects
                .select_related('boundary')
                .get(pk=self.value(), type=Region.Type.COUNTY)
            )
        except Region.DoesNotExist:
            return queryset
        return queryset.filter(boundary__geometry__intersects=county.boundary.geometry)


class BoundaryInline(LeafletMapMixin, admin.TabularInline):
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

        lmap = leaflet.LeafletMap(width=width, height=height)
        lmap.add(leaflet.Area(
            geometry=instance.geometry,
            fill_color='dodgerblue',
            border_color='royalblue',
        ))
        return lmap.render()
    get_map.short_description = 'Map'

@admin.register(Region)
class RegionAdmin(LeafletMapMixin, ReadOnlyAdminMixin, GISModelAdmin):
    inlines = [BoundaryInline]
    list_display = ['name', 'type', 'external_id', 'current_version', 'monitor_count']
    list_filter = ['type', CountyFilter, 'boundary__version']
    fields = ['name', 'slug', 'external_id', 'type', 'boundary', 'get_metadata', 'get_overview_map', 'get_monitor_map']
    search_fields = ['name', 'external_id']

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

    def get_metadata(self, instance):
        if not instance.metadata:
            return '-'
        return mark_safe(f'<pre>{yaml.dump(instance.metadata).strip()}</pre>')
    get_metadata.short_description = 'Metadata'

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
                'landscape': (400, 300),
                'portrait': (300, 400),
            }[county.orientation]

            lmap = leaflet.LeafletMap(width=width, height=height)

            if county.region_id != instance.pk:
                lmap.add(leaflet.Area(
                    geometry=county.geometry,
                    fill_color='white',
                    border_color='dimgrey',
                    fill_opacity=.5,
                ))

            lmap.add(leaflet.Area(
                geometry=instance.boundary.geometry,
                fill_color='dodgerblue',
                border_width=0,
                fill_opacity=1,
            ))

            return lmap.render()
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

            lmap = leaflet.LeafletMap(width=width, height=height)
            lmap.add(leaflet.Area(
                geometry=instance.boundary.geometry,
                fill_color='dodgerblue',
                border_color='royalblue',
                border_width=1,
            ))

            monitor_list = (
                instance.monitors
                .with_grade()
                .with_last_entry_timestamp()
                .order_by('grade', 'position')
                .with_latest_entry(entry_models.PM25)
            )

            active = 0
            for monitor in monitor_list:
                if monitor.is_active:
                    active += 1

                fill_color = monitor.latest_entry.Levels.get_color(
                    monitor.latest_entry.level.value
                ) if monitor.is_active else 'darkgray'

                border_color = _blend_hex(fill_color, '#000000', .2) if monitor.is_active else 'dimgray'

                lmap.add(leaflet.Marker(
                    geometry=monitor.position,
                    size=14 if monitor.is_active else 10,
                    fill_color=fill_color,
                    border_color=border_color,
                    shape='triangle' if monitor.is_regulatory else 'circle' if monitor.is_sjvair else 'square',
                    border_width=1,
                ))

            return mark_safe(f'''
                <div>{len(monitor_list)} Monitors ({active} Active, {len(monitor_list) - active} Inactive)</div>
                {lmap.render()}
            ''')
        except Exception:
            import traceback
            traceback.print_exc()
    get_monitor_map.short_description = 'Monitors'


@admin.register(Location)
class LocationAdmin(GISModelAdmin):
    list_display = ('name', 'type', 'city', 'county')
    list_filter = ('type', 'source')
    list_select_related = ('county', 'district')
    search_fields = ('name', 'external_id', 'city')
    raw_id_fields = ('county', 'district')
