from rangefilter.filters import NumericRangeFilterBuilder

from django.contrib.gis import admin
from django.contrib.gis.admin import OSMGeoAdmin
from django.urls import reverse
from django.utils.html import format_html

from .models import Record


#Filter for UI, set default as percentile bounds 0-100
CustomNumericRangeFilter = (
    NumericRangeFilterBuilder(
        default_start = 0,
        default_end = 100,
        )
    )


@admin.register(Record)
class Ces4Admin(OSMGeoAdmin):
    list_display = [
        'tract','pollution_p', 'pol_ozone',
        'pol_ozone_p', 'pol_pm', 'pol_pm_p', 'char_asthma', 'char_asthma_p', 
        ]
    list_filter = [
        ('pollution_p', CustomNumericRangeFilter), ('pol_ozone_p', CustomNumericRangeFilter),
        ('pol_pm_p', CustomNumericRangeFilter), ('char_asthma_p', CustomNumericRangeFilter),
        ]
    ordering = ('-ci_score_p', )
    search_fields = ['tract']
    readonly_fields = ['link_to_boundary']
    def link_to_boundary(self, instance):
        region = instance.boundary.region
        link = reverse("admin:regions_region_change", args=[region.pk])
        return format_html(
            '<a href="{}">{}</a>',
            link,
            instance.boundary,
        )
    link_to_boundary.short_description = "Boundary Link"
        
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    