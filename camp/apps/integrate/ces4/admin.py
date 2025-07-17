from rangefilter.filters import NumericRangeFilterBuilder

from django.contrib.gis import admin

from .models import Tract


#Filter for UI, set default as percentile bounds 0-100
CustomNumericRangeFilter = (
    NumericRangeFilterBuilder(
        default_start = 0,
        default_end = 100,
        )
    )


@admin.register(Tract)
class Ces4Admin(admin.GISModelAdmin):
    list_display = [
        'tract', 'county', 'pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p', 'char_asthma', 'char_asthma_p'
        ]
    list_filter = [
        ('pollution_p', CustomNumericRangeFilter), ('pol_ozone_p', CustomNumericRangeFilter),
        ('pol_pm_p', CustomNumericRangeFilter), ('char_asthma_p', CustomNumericRangeFilter), 'county', 
        ]
    ordering = ('-county', '-ci_score_p', )
    
    def get_readonly_fields(self, request, obj=None):
        return [
            f.name for f in self.model._meta.get_fields()
            if f.name != 'geometry'
        ]
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    