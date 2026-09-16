from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.html import format_html

register = template.Library()


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
    if value is None:
        return '—'
    return intcomma(int(round(value)))


@register.filter
def category_label(value):
    from camp.apps.pesticides.models import Chemical
    return dict(Chemical.Category.choices).get(value, value)
