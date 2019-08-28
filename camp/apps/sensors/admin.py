from django.contrib.gis import admin

from .models import Sensor, SensorData


@admin.register(Sensor)
class SensorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'position', 'location']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('latest')
        return queryset


@admin.register(SensorData)
class SensorDataAdmin(admin.OSMGeoAdmin):
    list_display = ['pk', 'sensor', 'timestamp', 'fahrenheit', 'humidity', 'pressure']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('sensor')
        return queryset
