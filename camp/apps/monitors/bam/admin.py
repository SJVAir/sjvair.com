from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.bam.models import BAM1022


@admin.register(BAM1022)
class BAM1022Admin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.remove('default_sensor')
    list_display.remove('get_current_health')
