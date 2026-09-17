from django import template

from camp.apps.reports.base import REPORTS

register = template.Library()


@register.simple_tag
def report_list():
    """Registered reports, in index order, for the admin sidebar."""
    return REPORTS


@register.filter
def get_item(mapping, key):
    return mapping.get(key)
