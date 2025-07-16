from rangefilter.filters import DateRangeFilterBuilder

from django.contrib.admin.views.main import ChangeList
from django.contrib.gis import admin
from django.db.models import Max, Min

from .models import Smoke


def CustomDateRangeFilter():
    return DateRangeFilterBuilder(
        default_start=Smoke.objects.aggregate(Min('date'))['date__min'],
        default_end=Smoke.objects.aggregate(Max('date'))['date__max'],
    )

class CustomChangeList(ChangeList):
    def get_filters_params(self, params=None):
        params = params or self.params.copy()
        if 'date__range__lte' in params:
            params['date__lte'] = params.pop('date__range__lte')
        if 'date__range__gte' in params:
            params['date__gte'] = params.pop('date__range__gte')

        return super().get_filters_params(params)


@admin.register(Smoke)
class SmokeAdmin(admin.GISModelAdmin):
    readonly_fields = ['id', 'satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_display = ['id', 'satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_filter = ['satellite', 'density', 
                   ('date', CustomDateRangeFilter()),
                   'is_final', ]
    ordering = ('-date', )
    
    def get_changelist(self, request, **kwargs):
        return CustomChangeList
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    