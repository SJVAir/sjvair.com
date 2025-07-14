from django.contrib import admin
from .models import Smoke

from rangefilter.filters import DateRangeFilterBuilder

@admin.register(Smoke)
class SmokeAdmin(admin.ModelAdmin):
    # date_hierarchy = 'date'
    list_display =['satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_filter = ['satellite', 'density', ('date', DateRangeFilterBuilder()), 'is_final', ]
    readonly_fields = ['id', 'satellite', 'density', 'is_final', 'start', 'end', 'geometry', ]
    ordering = ('-date', )
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    