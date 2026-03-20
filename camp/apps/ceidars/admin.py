from django.contrib.gis import admin
from django.db.models import Max

from .models import EmissionsRecord, Facility


class EmissionsRecordInline(admin.TabularInline):
    model = EmissionsRecord
    extra = 0
    readonly_fields = [
        'sqid', 'year',
        'tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
        'total_score', 'hra', 'chindex', 'ahindex',
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Facility)
class FacilityAdmin(admin.GISModelAdmin):
    list_display = ['name', 'county_code', 'sic_code', 'has_point', 'latest_year']
    list_filter = ['county_code']
    search_fields = ['name', 'address__city']
    readonly_fields = ['sqid', 'county_code', 'facid', 'metadata_year', 'point']
    inlines = [EmissionsRecordInline]
    actions = ['regeocode_selected']

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
