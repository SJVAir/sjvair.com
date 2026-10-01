"""Filters the explorers' shared area-page templates (templates/regions/) use."""
import math

from django import template
from django.contrib.humanize.templatetags.humanize import ordinal

register = template.Library()


@register.filter
def percentile(value):
    """
    A CalEnviroScreen percentile as an ordinal ("99th"), rounded down: OEHHA's
    top tracts score 99.5-99.99, which rounding would call a "100th"
    percentile no tract has.
    """
    if value is None:
        return ''
    return ordinal(max(1, math.floor(value)))


@register.filter
def whole_percent(share):
    """A 0-1 share as a whole percentage ("37%"), "<1%" for a sliver, a dash for none."""
    if share is None:
        return '—'
    if 0 < share < 0.01:
        return '<1%'
    return f'{share * 100:.0f}%'
