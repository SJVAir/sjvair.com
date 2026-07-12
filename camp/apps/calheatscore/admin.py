from django.contrib import admin

from .models import CalHeatScore


@admin.register(CalHeatScore)
class CalHeatScoreAdmin(admin.ModelAdmin):
    list_display = ['region', 'date', 'score', 'updated_at']
    list_filter = ['score', 'date']
    search_fields = ['region__external_id', 'region__name']
    readonly_fields = ['region', 'date', 'score', 'updated_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass
