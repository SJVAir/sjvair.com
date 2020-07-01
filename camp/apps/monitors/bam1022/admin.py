from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.bam.models import BAM1022


@admin.register(BAM1022)
class BAM1022Admin(MonitorAdmin):
    fields = MonitorAdmin.fields[:]
    fields.insert(1, 'auth_key')
