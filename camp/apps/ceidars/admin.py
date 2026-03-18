from django.contrib.gis import admin

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
    list_display = ['name', 'city', 'county_code', 'sic_code', 'has_position', 'latest_year']
    list_filter = ['county_code']
    search_fields = ['name', 'city']
    readonly_fields = ['sqid', 'county_code', 'facid', 'metadata_year', 'position']
    inlines = [EmissionsRecordInline]
    actions = ['regeocode_selected']

    @admin.display(boolean=True, description='Geocoded')
    def has_position(self, obj):
        return obj.position is not None

    @admin.display(description='Latest year')
    def latest_year(self, obj):
        record = obj.emissions.order_by('-year').first()
        return record.year if record else '—'

    @admin.action(description='Re-geocode selected facilities')
    def regeocode_selected(self, request, queryset):
        success = 0
        failed = 0
        for facility in queryset:
            if facility.geocode():
                facility.save(update_fields=['position'])
                success += 1
            else:
                failed += 1
        self.message_user(request, f'Geocoded {success} facilities. {failed} failures.')
