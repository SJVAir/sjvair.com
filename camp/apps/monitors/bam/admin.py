from django.contrib.gis import admin
from django.utils.translation import gettext_lazy as _

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.bam.models import BAM1022, BAMStatus


class BAMStatusInline(TabularInlinePaginated):
    model = BAMStatus
    extra = 0
    per_page = 50
    fields = ['timestamp', 'code', 'get_labels']
    readonly_fields = fields
    ordering = ['-timestamp']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=_('Alarms'))
    def get_labels(self, obj):
        return ', '.join(obj.labels)


@admin.register(BAM1022)
class BAM1022Admin(MonitorAdmin):
    inlines = MonitorAdmin.inlines + [BAMStatusInline]
    readonly_fields = MonitorAdmin.readonly_fields + ['get_status']
    fieldsets = [
        (None, {'fields': ['get_monitor_id', 'name', 'is_hidden', 'is_sjvair', 'get_status']}),
        *MonitorAdmin.fieldsets[1:],
    ]

    @admin.display(description=_('Current status'))
    def get_status(self, obj):
        if obj.status is None:
            return 'OK'
        return f'{", ".join(obj.status.labels)} ({obj.status.timestamp:%Y-%m-%d %H:%M} UTC)'


@admin.register(BAMStatus)
class BAMStatusAdmin(admin.ModelAdmin):
    list_display = ['monitor', 'timestamp', 'code', 'get_labels']
    list_filter = ['monitor']
    date_hierarchy = 'timestamp'
    readonly_fields = ['monitor', 'timestamp', 'code', 'get_labels']
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description=_('Alarms'))
    def get_labels(self, obj):
        return ', '.join(obj.labels)
