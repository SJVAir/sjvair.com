from django.contrib import admin

from .models import Forecast


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    date_hierarchy = 'forecast_date'
    list_display = ['zone_name', 'forecast_date', 'issued_date', 'aqi_value', 'aqi_category', 'burn_status', 'air_alert']
    list_filter = ['aqi_category', 'burn_status', 'air_alert']
    readonly_fields = [
        'sqid', 'region', 'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant', 'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    ]
    ordering = ('-issued_date', 'zone_name')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass
