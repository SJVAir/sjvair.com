from django.contrib.gis import admin

from .models import Smoke


@admin.register(Smoke)
class SmokeAdmin(admin.GISModelAdmin):
    date_hierarchy = 'date'
    readonly_fields = ['id', 'satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_display = ['id', 'satellite', 'density', 'date', 'start', 'end', 'is_final',]
    list_filter = ['satellite', 'density', 'is_final', ]
    ordering = ('-date', )
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        pass
    