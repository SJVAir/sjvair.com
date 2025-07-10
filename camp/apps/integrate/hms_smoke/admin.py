from django.contrib import admin
from .models import Smoke

@admin.register(Smoke)
class SmokeAdmin(admin.ModelAdmin):
    date_hierarchy = 'date'
    list_filter = ['satellite', 'density', 'is_final']
    readonly_fields = ['id', 'satellite', 'density', 'is_final', 'start', 'end', 'geometry']
    
    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    