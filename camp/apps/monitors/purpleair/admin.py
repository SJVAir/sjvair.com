from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db import models
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import LCSMonitorAdmin
from camp.apps.monitors.purpleair.models import PurpleAir, PurpleAirHistoryGap, PurpleAirHistoryJob


@admin.register(PurpleAir)
class PurpleAirAdmin(LCSMonitorAdmin):
    pass


@admin.register(PurpleAirHistoryJob)
class PurpleAirHistoryJobAdmin(admin.ModelAdmin):
    list_display = [
        'state', 'cursor', 'range_start', 'range_end', 'pending_tasks',
        'requests_made', 'raw_entries_created', 'consecutive_failures', 'modified',
    ]
    list_filter = ['state']
    ordering = ['-created']
    readonly_fields = [
        f.name for f in PurpleAirHistoryJob._meta.get_fields()
        if isinstance(f, models.Field) and f.name != 'state'
    ]


@admin.register(PurpleAirHistoryGap)
class PurpleAirHistoryGapAdmin(admin.ModelAdmin):
    list_display = ['monitor', 'window_start', 'window_end', 'reason', 'job']
    list_filter = ['reason']
    ordering = ['-created']
