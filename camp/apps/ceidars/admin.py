from django.contrib.gis import admin
from django.db.models import Max

from .models import EmissionsRecord, Facility


class EmissionsRecordInline(admin.TabularInline):
    model = EmissionsRecord
    extra = 0
    readonly_fields = [
        'year',
        'tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
        'total_score', 'hra', 'chindex', 'ahindex',
        'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
        'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
        'methylene_chloride', 'naphthalene', 'perchloroethylene',
    ]
    fields = readonly_fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Facility)
class FacilityAdmin(admin.GISModelAdmin):
    list_display = ['name', 'get_county', 'get_city', 'get_zipcode', 'sic_code', 'is_minor_source', 'has_point', 'latest_year']
    list_filter = ['county', 'city']
    search_fields = ['name', 'address__street', 'address__city']
    readonly_fields = ['sqid', 'county_code', 'facid', 'metadata_year', 'point']
    inlines = [EmissionsRecordInline]
    actions = ['regeocode_selected']

    fieldsets = [
        (None, {
            'fields': ['sqid', ('county_code', 'facid'), 'name', 'sic_code', 'metadata_year'],
        }),
        ('Location', {
            'fields': ['address', 'point'],
        }),
        ('Regions', {
            'fields': ['county', 'zipcode', 'city'],
        }),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            latest_emission_year=Max('emissions__year')
        )

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
