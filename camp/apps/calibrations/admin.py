from django import forms
from django.contrib import admin
from django.db.models import Prefetch
from django.template import Context, Template
from django.urls import reverse
from django.utils.safestring import mark_safe

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.monitors.models import Monitor, Entry
from .forms import DefaultCalibrationForm
from .models import Calibrator, AutoCalibration, DefaultCalibration


def formula_help_text():
    return mark_safe(Template('''
        <p>&#128279; <a href="https://github.com/AxiaCore/py-expression-eval/#available-operators-constants-and-functions">Available operators, constants, and functions.</a></p>
        <p><b>Available variables:</b></p>
        <ul>
            {% for env in environment %}<li><code>{{ env }}</code></li>{% endfor %}
        </ul>
    ''').render(Context({'environment': Entry.ENVIRONMENT})))


@admin.register(DefaultCalibration)
class DefaultCalibrationAdmin(admin.ModelAdmin):
    form = DefaultCalibrationForm
    list_display = ('monitor_type', 'entry_type', 'calibration')
    list_filter = ('monitor_type', 'entry_type')
    search_fields = ('monitor_type', 'entry_type', 'calibration')

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj  # for formfield_for_dbfield
        return super().get_form(request, obj=obj, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'calibration':
            if instance := getattr(request, '_obj_', None):
                kwargs['widget'].choices = self.form.get_calibration_choices(instance)
        return super().formfield_for_dbfield(db_field, request, **kwargs)



class AutoCalibrationInline(TabularInlinePaginated):
    extra = 0
    model = AutoCalibration
    per_page = 30
    fields = ('start_date', 'end_date', 'r2', 'formula')
    readonly_fields = ('start_date', 'end_date', 'r2', 'formula')

    def has_add_permission(self, request, obj):
        # Calibrations are added automatically.
        return False

    def has_change_permission(self, request, obj):
        # Calibrations are added automatically.
        return False


@admin.register(Calibrator)
class CalibratorAdmin(admin.ModelAdmin):
    inlines = (AutoCalibrationInline,)
    list_display = ('pk', 'get_reference', 'get_colocated', 'get_county', 'get_distance', 'is_enabled', 'get_r2', 'get_last_updated',)
    list_filter = ('is_enabled', 'reference__county', 'calibration__end_date',)
    raw_id_fields = ('reference', 'colocated', 'calibration')

    def get_queryset(self, request):
        monitor_queryset = Monitor.objects.all().select_related('latest')

        queryset = super().get_queryset(request)
        queryset = queryset.select_related('calibration')
        queryset = queryset.prefetch_related(
            Prefetch('reference', monitor_queryset),
            Prefetch('colocated', monitor_queryset),
        )
        return queryset

    def get_county(self, instance):
        return instance.reference.county
    get_county.short_description = 'County'

    def get_distance(self, instance):
        distance = instance.get_distance()
        context = {'distance': int(round(distance.feet)), 'unit': 'ft'}
        if distance.feet > 1000:
            context = {'distance': distance.miles, 'unit': 'mi'}
        return (Template('{% load humanize %}{{ distance|floatformat|intcomma }} {{ unit }}')
            .render(Context(context))
        )
    get_distance.short_description = 'Distance'

    def get_last_updated(self, instance):
        if instance.calibration:
            return instance.calibration.end_date
        return '-'
    get_last_updated.short_description = 'Last Updated'
    get_last_updated.admin_order_field = 'calibration__end_date'

    def get_r2(self, instance):
        if instance.calibration:
            return instance.calibration.r2
        return '-'
    get_r2.short_description = 'R2'
    get_r2.admin_order_field = 'calibration__r2'

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
        return self.get_monitor_link(instance.reference)
    get_reference.short_description = 'Reference Monitor'

    def get_colocated(self, instance):
        return self.get_monitor_link(instance.colocated)
    get_colocated.short_description = 'Colocated Monitor'
