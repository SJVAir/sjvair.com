import pytz
from django.template.loader import render_to_string

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.qaqc.models import HealthCheck


class HealthCheckInline(TabularInlinePaginated):
    extra = 0
    model = HealthCheck
    per_page = 24
    fields = ('get_hour', 'score', 'grade', 'variance', 'correlation', 'view_chart')
    readonly_fields = fields
    ordering = ['-created']
    can_delete = False

    def view_chart(self, instance):
        return render_to_string("admin/qaqc/analysis-chart.html", {
            'analysis': instance,
        })

    def get_hour(self, instance):
        return instance.hour.astimezone(pytz.timezone('America/Los_Angeles'))
    get_hour.short_description = 'Hour'

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False

