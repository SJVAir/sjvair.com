from django.contrib import admin
from .models import Tract

from admin_numeric_filter.admin import RangeNumericFilter


@admin.register(Tract)
class Ces4Admin(admin.ModelAdmin):
    list_display = [
        'tract', 'population', 'county', 'ci_score', 
        'ci_score_p', 'pollution', 'pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p'
        ]
    
    list_filter = [
        ('ci_score_p', RangeNumericFilter), 
        ('pollution_p', RangeNumericFilter), ('pol_ozone_p', RangeNumericFilter),
        ('pol_pm_p', RangeNumericFilter), 'county', 
        ]
    
    ordering = ('-county', '-ci_score', )
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    