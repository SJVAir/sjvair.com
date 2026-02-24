from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import Inversion, RadiationInversion, SubsidenceInversion, FrontalInversion


@admin.register(Inversion)
class InversionAdmin(GISModelAdmin):
    list_display = [
        'id',
        'inversion_type',
        'severity',
        'detected_at',
        'persistence_hours',
        'pm25_confirmed',
        'is_active',
    ]
    list_filter = [
        'inversion_type',
        'severity',
        'pm25_confirmed',
        'is_active',
        'detected_at',
    ]
    search_fields = ['notes']
    readonly_fields = ['detected_at']
    fieldsets = (
        (
            'Basic Information',
            {
                'fields': (
                    'location',
                    'inversion_type',
                    'severity',
                    'detected_at',
                    'period',
                )
            },
        ),
        (
            'Meteorological Data',
            {
                'fields': (
                    'temperature_gradient',
                    'surface_temperature',
                    'upper_air_temperature',
                    'wind_speed',
                    'pressure',
                    'boundary_layer_height',
                )
            },
        ),
        (
            'Inversion Characteristics',
            {'fields': ('strength', 'confidence', 'persistence_hours')},
        ),
        (
            'PM2.5 Confirmation',
            {
                'fields': (
                    'pm25_confirmed',
                    'pm25_night_mean',
                    'pm25_day_mean',
                    'pm25_previous_day_mean',
                    'pm25_night_day_ratio',
                )
            },
        ),
        ('Additional Info', {'fields': ('notes', 'is_active')}),
    )


@admin.register(RadiationInversion)
class RadiationInversionAdmin(admin.ModelAdmin):
    list_display = ['id', 'inversion', 'time_of_day', 'cloud_cover']
    list_filter = ['time_of_day']


@admin.register(SubsidenceInversion)
class SubsidenceInversionAdmin(admin.ModelAdmin):
    list_display = ['id', 'inversion', 'pressure_system', 'inversion_height']
    list_filter = ['pressure_system']


@admin.register(FrontalInversion)
class FrontalInversionAdmin(admin.ModelAdmin):
    list_display = ['id', 'inversion', 'front_type']
    list_filter = ['front_type']
