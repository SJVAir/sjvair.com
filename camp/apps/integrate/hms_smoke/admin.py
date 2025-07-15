from rangefilter.filters import DateRangeFilterBuilder

from django.contrib import admin
from django.db.models import Max, Min

from .models import Smoke

@admin.register(Smoke)
class SmokeAdmin(admin.ModelAdmin):
    list_display =['satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_filter = ['satellite', 'density', 
                   ('date', DateRangeFilterBuilder(
                       default_start=Smoke.objects.aggregate(Min('date'))['date__min'],
                       default_end=Smoke.objects.aggregate(Max('date'))['date__max'],
                       )), 
                   'is_final', ]
    ordering = ('-date', )
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    