from django.contrib import admin
#from django.db.models import Prefetch
from django.template import Context, Template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.monitors.models import Monitor 
from .models import SensorAnalysis

#class SensorAnalysisInline(TabularInlinePaginated):
#    extra = 0
#    model = Monitor
#    per_page = 30
#    fields = ('id', 'name', 'is_active')
#    readonly_fields = ('id', 'name', 'is_active')
#
#    def has_add_permission(self, request, obj):
#        return False
#
#    def has_change_permission(self, request, obj):
#        return False


@admin.register(SensorAnalysis)
class SensorAnalysisAdmin(admin.ModelAdmin):
    #inlines = (SensorAnalysisInline,)
    list_display = ('pk', 'get_reference', 'start_date', 'end_date', 'r2', 'coef', 'intercept')
    readonly_fields = ('pk', 'get_reference', 'start_date', 'end_date', 'r2', 'coef', 'intercept')
    exclude = ['monitor']

    def get_monitor_link(self, instance):
        return mark_safe(Template('''
            {% load static %}
            {% if monitor.is_active %}
                <img src="{% static 'admin/img/icon-yes.svg' %}" alt="Active">
            {% else %}
                <img src="{% static 'admin/img/icon-no.svg' %}" alt="Inctive">
            {% endif %}
            <a href="{{ url }}">{{ monitor.name }}</a> ({{ monitor_type }})
        ''').render(Context({
            'monitor': instance,
            'monitor_type': instance.__class__.__name__,
            'url': reverse(f'admin:{instance._meta.app_label}_{instance._meta.model_name}_change', args=[str(instance.pk)])
        })))

    def get_reference(self, instance):
        return self.get_monitor_link(instance.monitor)
    get_reference.short_description = 'Monitor'

