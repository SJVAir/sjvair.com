from django.contrib import admin

from camp.utils.admin import ReadOnlyAdminMixin, admin_change_link

from .models import Forecast


@admin.register(Forecast)
class ForecastAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    date_hierarchy = 'forecast_date'
    list_display = [
        'zone_name', 'get_region', 'forecast_date', 'issued_date',
        'aqi_value', 'aqi_category', 'pollutant', 'burn_status', 'air_alert',
    ]
    list_filter = ['aqi_category', 'pollutant', 'burn_status', 'air_alert']
    search_fields = ['zone_name', 'region__name']
    ordering = ('-issued_date', 'zone_name')
    fields = [
        'region', 'zone_name',
        'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant',
        'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('region')

    def get_region(self, instance):
        return admin_change_link(instance.region, instance.region.name)
    get_region.short_description = 'Region'
    get_region.admin_order_field = 'region__name'
