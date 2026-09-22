from django.contrib import admin as base_admin
from django.contrib.gis import admin
from django.db.models import Max
from django.urls import reverse
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region
from camp.utils import leaflet
from camp.utils.admin import LeafletMapMixin, ReadOnlyAdminMixin

from .models import EmissionsRecord, Facility


class CountyFilter(base_admin.SimpleListFilter):
    title = 'county'
    parameter_name = 'county'

    def lookups(self, request, model_admin):
        counties = Region.objects.filter(type=Region.Type.COUNTY).order_by('name')
        return [(c.pk, c.name) for c in counties]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(county_id=self.value())
        return queryset


class EmissionsYearFilter(base_admin.SimpleListFilter):
    title = 'emissions year'
    parameter_name = 'year'

    def lookups(self, request, model_admin):
        years = (
            EmissionsRecord.objects
            .values_list('year', flat=True)
            .distinct()
            .order_by('-year')
        )
        return [(y, y) for y in years]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(emissions__year=self.value())
        return queryset


class SourceTypeFilter(base_admin.SimpleListFilter):
    title = 'source type'
    parameter_name = 'source_type'

    def lookups(self, request, model_admin):
        return [('major', 'Major'), ('minor', 'Minor')]

    def queryset(self, request, queryset):
        if self.value() == 'major':
            return queryset.major_sources()
        if self.value() == 'minor':
            return queryset.minor_sources()
        return queryset


class EmissionsRecordInline(admin.TabularInline):
    model = EmissionsRecord
    extra = 0
    can_delete = False

    ALL_FIELDS = [
        'year',
        'tog', 'rog', 'co', 'nox', 'sox', 'pm', 'pm10',
        'total_score', 'hra', 'chindex', 'ahindex',
        'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
        'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
        'methylene_chloride', 'naphthalene', 'perchloroethylene',
    ]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['year']
        aggregates = obj.emissions.aggregate(**{
            field: Max(field) for field in self.ALL_FIELDS[1:]
        })
        return ['year'] + [field for field, val in aggregates.items() if val is not None]

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Facility)
class FacilityAdmin(LeafletMapMixin, ReadOnlyAdminMixin, admin.GISModelAdmin):
    list_display = ['name', 'get_county', 'air_district', 'get_city', 'get_zipcode', 'sic_code', 'sector', 'is_minor_source', 'has_point', 'latest_year']
    list_filter = [CountyFilter, 'air_district', 'sector', EmissionsYearFilter, SourceTypeFilter]
    search_fields = ['name', 'address__street', 'address__city']
    readonly_fields = ['sqid', 'county_code', 'air_district', 'facid', 'name', 'sic_code', 'sector', 'metadata_year', 'address', 'point', 'get_county_display', 'get_city_display', 'get_zipcode_display']
    inlines = [EmissionsRecordInline]
    actions = ['regeocode_selected']

    fieldsets = [
        (None, {
            'fields': ['sqid', ('county_code', 'air_district', 'facid'), 'name', ('sic_code', 'sector'), 'metadata_year'],
        }),
        ('Location', {
            'fields': ['address', 'point'],
        }),
        ('Regions', {
            'fields': [
                'get_county_display',
                'get_city_display',
                'get_zipcode_display',
            ],
        }),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            latest_emission_year=Max('emissions__year')
        )

    def _render_region_map(self, facility, region):
        if not region or not region.boundary:
            return None
        boundary = region.boundary
        width, height = {'landscape': (400, 300), 'portrait': (300, 400)}[boundary.orientation]
        lmap = leaflet.LeafletMap(width=width, height=height)
        lmap.add(leaflet.Area(
            geometry=boundary.geometry,
            fill_color='DodgerBlue',
            border_color='MidnightBlue',
            border_width=1,
            fill_opacity=0.2,
        ))
        if facility.point:
            lmap.add(leaflet.Marker(
                geometry=facility.point,
                shape='star',
                size=22,
                fill_color='Crimson',
                border_color='White',
                border_width=1,
            ))
        return lmap.render()

    def _render_region_display(self, facility, region):
        if not region:
            return '-'
        url = reverse('admin:regions_region_change', args=[region.pk])
        html = f'<a href="{url}">{region.name}</a>'
        map_content = self._render_region_map(facility, region)
        if map_content:
            html += f'<br>{map_content}'
        return mark_safe(html)

    @admin.display(description='County')
    def get_county_display(self, facility):
        return self._render_region_display(facility, facility.county)

    @admin.display(description='City')
    def get_city_display(self, facility):
        return self._render_region_display(facility, facility.city)

    @admin.display(description='Zipcode')
    def get_zipcode_display(self, facility):
        return self._render_region_display(facility, facility.zipcode)

    @admin.display(boolean=True, description='Geocoded')
    def has_point(self, obj):
        return obj.point is not None

    @admin.display(description='Latest year')
    def latest_year(self, obj):
        return obj.latest_emission_year or '—'

    @admin.action(description='Re-geocode selected facilities')
    def regeocode_selected(self, request, queryset):
        success = 0
        failed = 0
        for facility in queryset:
            if facility.geocode():
                facility.save(update_fields=['point'])
                success += 1
            else:
                failed += 1
        self.message_user(request, f'Geocoded {success} facilities. {failed} failures.')
