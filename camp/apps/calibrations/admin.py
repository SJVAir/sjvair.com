from django.contrib import admin
from django.template import Context, Template

from .models import Calibrator, Calibration


class CalibrationInline(admin.TabularInline):
    extra = 0
    model = Calibration
    fields = ('start_date', 'end_date', 'r2', 'formula')
    readonly_fields = ('start_date', 'end_date', 'r2', 'formula')


@admin.register(Calibrator)
class CalibratorAdmin(admin.ModelAdmin):
    inlines = (CalibrationInline,)
    list_display = ('pk', 'reference', 'colocated', 'format_distance')
    raw_id_fields = ('reference', 'colocated', 'calibration')

    def format_distance(self, instance):
        distance = instance.get_distance().meters
        unit = 'm'
        if distance >= 1000:
            distance /= 1000
            unit = 'km'
        return (Template('{% load humanize %}{{ distance|floatformat|intcomma }} {{ unit }}')
            .render(Context({
                'distance': distance,
                'unit': unit,
            }))
        )
    format_distance.short_description = 'Distance'
