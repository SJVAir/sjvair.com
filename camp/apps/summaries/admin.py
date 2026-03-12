from django.contrib import admin
from django.db.models import Field

from camp.apps.summaries.models import MonitorSummary, RegionSummary


def _readonly(model):
    return [f.name for f in model._meta.get_fields() if isinstance(f, Field)]


@admin.register(MonitorSummary)
class MonitorSummaryAdmin(admin.ModelAdmin):
    list_display = ['monitor', 'entry_type', 'stage', 'processor', 'resolution', 'timestamp', 'mean', 'count', 'is_complete']
    list_filter = ['resolution', 'entry_type', 'stage', 'is_complete']
    search_fields = ['monitor__name']
    ordering = ['-timestamp']
    readonly_fields = _readonly(MonitorSummary)


@admin.register(RegionSummary)
class RegionSummaryAdmin(admin.ModelAdmin):
    list_display = ['region', 'entry_type', 'stage', 'processor', 'resolution', 'timestamp', 'mean', 'station_count', 'is_complete']
    list_filter = ['resolution', 'entry_type', 'stage', 'is_complete']
    search_fields = ['region__name']
    ordering = ['-timestamp']
    readonly_fields = _readonly(RegionSummary)
