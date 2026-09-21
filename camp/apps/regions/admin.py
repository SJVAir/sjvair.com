import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.entries import models as entry_models
from camp.apps.entries.levels import _blend_hex
from camp.apps.regions.models import Region, Boundary
from camp.apps.regions.panels import panels_for
from camp.utils import leaflet
from camp.utils.admin import LeafletMapMixin, ReadOnlyAdminMixin

# Marker outline for SJVAir-owned monitors on the region map.
SJVAIR_BORDER = '#0a84ff'


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
    classes = ['collapse']
    verbose_name_plural = 'Boundaries'
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
    # The monitor map is rendered by the change form itself (beside the tiles);
    # see admin/regions/region/change_form.html.
    fieldsets = [
        ('Region', {
            'classes': ['collapse'],
            'fields': ['name', 'slug', 'external_id', 'type', 'boundary', 'get_metadata', 'get_overview_map'],
        }),
    ]
    search_fields = ['name', 'external_id']

    def get_queryset(self, *args, **kwargs):
        queryset = (super()
            .get_queryset(*args, **kwargs)
            .select_related('boundary')
            .with_monitor_count()
        )
        return queryset

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Type-specific detail panels (camp.apps.regions.panels) render below
        # the fields; see admin/regions/region/change_form.html.
        region = self.get_object(request, object_id)
        panels = panels_for(region, request) if region is not None else []
        controls, seen = [], set()
        for panel in panels:
            for label, kind, links in panel.controls():
                if label not in seen:
                    seen.add(label)
                    controls.append((label, kind, links))
        extra_context = {
            **(extra_context or {}),
            'panels': panels,
            'tiles': [tile for panel in panels for tile in panel.tiles()],
            'controls': controls,
            'monitor_map': self.get_monitor_map(region) if region is not None else '',
            'county_name': self.county_name(region) if region is not None else '',
        }
        return super().change_view(request, object_id, form_url, extra_context)

    @staticmethod
    def county_name(region):
        """The SJV county this region sits in (by centroid), '' for a county or an outsider."""
        if region.type == Region.Type.COUNTY or not region.boundary_id:
            return ''
        return (Region.objects.counties()
            .filter(boundary__geometry__contains=region.boundary.geometry.centroid)
            .values_list('name', flat=True).first() or '')

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
                'landscape': (640, 440),
                'portrait': (440, 520),
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

                if monitor.is_sjvair:
                    border_color = SJVAIR_BORDER
                elif monitor.is_active:
                    border_color = _blend_hex(fill_color, '#000000', .2)
                else:
                    border_color = 'dimgray'

                lmap.add(leaflet.Marker(
                    geometry=monitor.position,
                    size=14 if monitor.is_active else 10,
                    fill_color=fill_color,
                    border_color=border_color,
                    shape='triangle' if monitor.is_regulatory else 'circle',
                    border_width=2 if monitor.is_sjvair else 1,
                ))

            return mark_safe(lmap.render())
        except Exception:
            import traceback
            traceback.print_exc()
    get_monitor_map.short_description = 'Monitors'
