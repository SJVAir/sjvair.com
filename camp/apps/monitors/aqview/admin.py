from django.contrib.gis import admin
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import floatformat

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.aqview.models import AQview
from camp.utils.forms import DateRangeForm


@admin.register(AQview)
class AQviewAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.remove('get_health_grade')

    fields = MonitorAdmin.fields
    readonly_fields = ['name', 'location', 'position', 'county']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def render_change_form(self, request, context, *args, **kwargs):
        context.update({'export_form': DateRangeForm()})
        return super().render_change_form(request, context, *args, **kwargs)
