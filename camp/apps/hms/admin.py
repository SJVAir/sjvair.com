from django.contrib.gis import admin

from .models import Fire, Smoke


@admin.register(Smoke)
class SmokeAdmin(admin.GISModelAdmin):
    date_hierarchy = 'date'
    list_display = ['id', 'date', 'satellite', 'density', 'start', 'end']
    list_filter = ['satellite', 'density']
    readonly_fields = ['id', 'date', 'satellite', 'density', 'start', 'end']
    ordering = ('-date',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass


@admin.register(Fire)
class FireAdmin(admin.GISModelAdmin):
    date_hierarchy = 'date'
    list_display = ['id', 'date', 'satellite', 'timestamp', 'frp', 'method']
    list_filter = ['satellite', 'method']
    readonly_fields = ['id', 'date', 'satellite', 'timestamp', 'frp', 'ecosystem', 'method']
    ordering = ('-date',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass
