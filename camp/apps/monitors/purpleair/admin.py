from django.contrib.admin.options import csrf_protect_m
from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import LCSMonitorAdmin
from camp.apps.monitors.purpleair.models import PurpleAir


@admin.register(PurpleAir)
class PurpleAirAdmin(LCSMonitorAdmin):
    pass
