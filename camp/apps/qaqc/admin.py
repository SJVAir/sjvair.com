import pytz
from django.contrib import admin
#from django.db.models import Prefetch
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.monitors.models import Monitor 
from .models import SensorAnalysis

class SensorAnalysisInline(TabularInlinePaginated):
    extra = 0
    model = SensorAnalysis
    per_page = 7
    fields = ('get_created', 'get_grade', 'r2', 'start_date', 'end_date', 'view_chart')
    readonly_fields = fields
    ordering = ('-created',)
    can_delete = False

    def view_chart(self, instance):
        return render_to_string("admin/qaqc/analysis-chart.html", {
            'analysis': instance,
        })

    def get_created(self, instance):
        return (instance.created.astimezone(pytz.timezone('America/Los_Angeles'))
                .strftime('%b. %d, %Y, %-I:%M %P'))
    get_created.short_description = "Created"

    def get_grade(self, instance):
        return instance.grade
    get_grade.short_description = "Grade"

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


@admin.register(SensorAnalysis)
class SensorAnalysisAdmin(admin.ModelAdmin):
    list_display = ('pk', 'get_reference', 'start_date', 'end_date', 'r2', 'coef', 'intercept')
    readonly_fields = ('pk', 'get_reference', 'start_date', 'end_date', 'r2', 'coef', 'intercept')
    search_fields = ['monitor__name']
    exclude = ['monitor']

    def get_monitor_link(self, instance):
        return render_to_string("admin/qaqc/monitor_link.html", {
            'monitor': instance,
            'monitor_type': instance.__class__.__name__,
            'url': reverse(
                f'admin:{instance._meta.app_label}_{instance._meta.model_name}_change',
                args=[str(instance.pk)]
            )
        })

    def get_reference(self, instance):
        return self.get_monitor_link(instance.monitor)
    get_reference.short_description = 'Monitor'

