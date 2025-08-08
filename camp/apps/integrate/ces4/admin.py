from rangefilter.filters import NumericRangeFilterBuilder

from django.contrib.gis import admin
from django.contrib.gis.admin import OSMGeoAdmin

from .models import Record
from camp.apps.regions.admin import BoundaryInline


#Filter for UI, set default as percentile bounds 0-100
CustomNumericRangeFilter = (
    NumericRangeFilterBuilder(
        default_start = 0,
        default_end = 100,
        )
    )


@admin.register(Record)
class Ces4Admin(OSMGeoAdmin):
    inlines = [BoundaryInline]
    list_display = [
        'tract','pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p', 'char_asthma', 'char_asthma_p', 
        ]
    # readonly_fields = ['boundary']
    list_filter = [
        ('pollution_p', CustomNumericRangeFilter), ('pol_ozone_p', CustomNumericRangeFilter),
        ('pol_pm_p', CustomNumericRangeFilter), ('char_asthma_p', CustomNumericRangeFilter),
        ]
    ordering = ('-ci_score_p', )
    search_fields = ['tract']
        
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    