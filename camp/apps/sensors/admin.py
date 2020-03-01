from django.contrib.gis import admin

from .models import Sensor, SensorData
from camp.utils.forms import DateRangeForm


@admin.register(Sensor)
class SensorAdmin(admin.OSMGeoAdmin):
    list_display = ['name', 'position', 'location']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('latest')
        return queryset

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)


@admin.register(SensorData)
class SensorDataAdmin(admin.OSMGeoAdmin):
    list_display = ['pk', 'sensor', 'timestamp', 'fahrenheit', 'humidity', 'pressure']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('sensor')
        return queryset
