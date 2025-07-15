from rangefilter.filters import NumericRangeFilterBuilder

from django.contrib import admin

from .models import Tract

#Filter for UI, set default as percentile bounds 0-100
CustomNumericRangeFilter = (
    NumericRangeFilterBuilder(
        default_start = 0,
        default_end = 100,
        )
    )
@admin.register(Tract)
class Ces4Admin(admin.ModelAdmin):
    list_display = [
        'tract', 'county', 'pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p', 'char_asthma', 'char_asthma_p'
        ]
    list_filter = [
        ('pollution_p', CustomNumericRangeFilter), ('pol_ozone_p', CustomNumericRangeFilter),
        ('pol_pm_p', CustomNumericRangeFilter), ('char_asthma_p', CustomNumericRangeFilter), 'county', 
        ]
    ordering = ('-county', '-ci_score_p', )
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    