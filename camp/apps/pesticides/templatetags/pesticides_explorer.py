import calendar

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.urls import reverse
from django.utils.html import format_html

from camp.apps.pesticides import notes as notes_module

register = template.Library()


@register.simple_tag
def region_url(region):
    if region is None:
        return ''
    return reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': region.slug})


@register.simple_tag(takes_context=True)
def qs_replace(context, **kwargs):
    """
    Current query string with the given keys replaced. A value of None or ''
    removes the key. Returns '' when nothing remains, otherwise '?a=b&c=d'.
    """
    params = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value is None or value == '':
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f'?{encoded}' if encoded else '?'


@register.simple_tag(takes_context=True)
def sort_link(context, key, label):
    """
    Column header link. Clicking the active column flips direction; clicking
    another column sorts descending for numeric-style keys ('lbs', counts) and
    ascending for 'name'. Always resets `page`.
    """
    current = context.get('sort') or ''
    active = current.lstrip('-') == key
    descending = current.startswith('-')
    if active:
        target = key if descending else f'-{key}'
        icon = 'fa-arrow-down-wide-short' if descending else 'fa-arrow-up-short-wide'
    else:
        target = 'name' if key == 'name' else f'-{key}'
        icon = 'fa-arrow-up-arrow-down'
    href = qs_replace(context, sort=target, page=None)
    css = 'sort-link is-active' if active else 'sort-link'
    return format_html(
        '<a class="{}" href="{}">{} <span class="icon is-small"><span class="fa-regular {}"></span></span></a>',
        css, href, label, icon,
    )


@register.filter
def lbs(value):
    """Whole pounds with commas; below ten pounds keep a decimal, below one keep two ("0.19"), so a bait's few ounces don't read as nothing."""
    if value is None:
        return '—'
    if value and abs(value) < 1:
        return f'{value:.2f}'
    if value and abs(value) < 10:
        return f'{value:.1f}'
    return intcomma(int(round(value)))


@register.filter
def month_abbr(value):
    return calendar.month_abbr[value]


@register.filter
def month_name(value):
    return calendar.month_name[value]


@register.filter
def max_lbs(by_month):
    return max((month['lbs'] for month in by_month), default=0)


@register.filter
def category_label(value):
    from camp.apps.pesticides.models import Chemical
    return dict(Chemical.Category.choices).get(value, value)


@register.simple_tag
def health_note(key):
    return notes_module.note(key)


@register.simple_tag
def iarc_note(chemical):
    if not chemical.iarc_group:
        return None
    return notes_module.note(f'iarc_{chemical.iarc_group.lower()}')


@register.filter
def note_summary(key):
    entry = notes_module.note(key)
    return entry['summary'] if entry else ''


@register.simple_tag
def elided_page_range(page_obj):
    """Page numbers around the current page with ellipses, for Bulma's pagination list."""
    paginator = page_obj.paginator
    return [
        (None if item == paginator.ELLIPSIS else item)
        for item in paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    ]
