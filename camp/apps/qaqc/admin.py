import pytz

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from django_admin_inline_paginator.admin import TabularInlinePaginated

from camp.apps.qaqc.models import HealthCheck
from camp.datasci import series

# TODO: move into utils for re-use elsewhere?
def format_percent(value, decimals=2):
    return f'{value * 100:.{decimals}f}%' if value is not None else '-'

def format_float(value, decimals=2):
    return f'{value:.{decimals}f}' if value is not None else '-'

def format_icon(value, alt=''):
    icon = {
        True: 'yes',
        False: 'no'
    }.get(value, 'alert')
    return render_to_string('admin/_includes/icon.html', {
        'icon': f'admin/img/icon-{icon}.svg',
        'alt': alt,
    })

def format_field(val, f):
    if isinstance(val, bool):
        return format_icon(val)
    if isinstance(val, int):
        return val
    if 'flatline' in f or 'completeness' in f:
        return format_percent(val, 0)
    if 'rpd' in f or f in {'correlation'}:
        return format_percent(val)
    return format_float(val)


class HealthCheckInline(TabularInlinePaginated):
    # Get base comparison fields (skip 'a' and 'b', which are nested)
    base_fields = [f for f in series.SeriesComparison._fields if f not in {'a', 'b'}]

    # Get summary fields from SeriesSummary
    summary_fields = ['completeness'] + list(series.SeriesSummary._fields)
    sanity_fields = ['completeness', 'max', 'flatline']

    extra = 0
    model = HealthCheck
    per_page = 24
    fields = (
        ['get_hour', 'score', 'grade']
        + [f'{f}_display' for f in base_fields]
        + ['get_channels']
        + [f'sanity_{f}_display' for f in sanity_fields]
        + [f'{f}_display' for f in summary_fields]
        # + ['a_summary', 'b_summary']
    )
    readonly_fields = fields
    ordering = ['-created']
    can_delete = False

    for field in base_fields:
        def make_display(f):
            def display(self, obj):
                val = getattr(obj, f)
                return format_field(val, f)
            display.short_description = f.replace('_', ' ').title()
            display.admin_order_field = f
            return display
        locals()[f'{field}_display'] = make_display(field)

    for field in summary_fields:
        def make_display(f):
            def display(self, obj):
                val_a = format_field(getattr(obj, f'{f}_a'), f)
                val_b = format_field(getattr(obj, f'{f}_b'), f)
                return self.channel_display(val_a, val_b)
            display.short_description = f.replace('_', ' ').title()
            return display
        locals()[f'{field}_display'] = make_display(field)

    for field in sanity_fields:
        def make_display(f):
            def display(self, obj):
                val_a = format_icon(getattr(obj, f'sanity_{f}_a'), 'Pass')
                val_b = format_icon(getattr(obj, f'sanity_{f}_b'), 'Fail')
                return self.channel_display(val_a, val_b)
            display.short_description = f[0].upper()
            return display
        locals()[f'sanity_{field}_display'] = make_display(field)

    def channel_display(self, a, b):
        return mark_safe(f'{a}<br />{b}')

    def get_channels(self, instance):
        return self.channel_display(
            '<span style="white-space: nowrap;">A|1:</span>',
            '<span style="white-space: nowrap;">B|2:</span>'
        )
    get_channels.short_description = ''

    def view_chart(self, instance):
        return render_to_string("admin/qaqc/analysis-chart.html", {
            'analysis': instance,
        })

    def get_hour(self, instance):
        hour = instance.hour.astimezone(pytz.timezone('America/Los_Angeles'))
        date = hour.strftime('%Y-%m-%d')
        time = hour.strftime('%-I %p (%Z)')
        return mark_safe(f'{date}<br /><b>{time}</b>')
    get_hour.short_description = 'Hour'

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False

