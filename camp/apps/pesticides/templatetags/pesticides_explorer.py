import calendar
import re

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.urls import reverse
from django.utils.html import format_html

from camp.apps.pesticides import notes as notes_module
from camp.apps.pesticides import stats

register = template.Library()


@register.simple_tag
def region_url(region):
    if region is None:
        return ''
    return region.get_pesticides_url()


@register.simple_tag(takes_context=True)
def qs_replace(context, **kwargs):
    """
    Current URL with the given query-string keys replaced. A value of None or
    '' removes the key. '?a=b&c=d' while anything remains, and the bare path
    once nothing does -- a lone '?' would be a link to the same page that
    still reads as a query string.
    """
    request = context['request']
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == '':
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f'?{encoded}' if encoded else request.path


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


# A word, with an apostrophe inside it kept ("CHILDREN'S" -> "Children's").
# Letters rather than [A-Za-z] so an accented name ("CANADA" with a tilde)
# doesn't come back out half-shouted.
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


@register.filter
def title_case_name(value):
    """
    A shouted source name as a readable one: "SELMA  HIGH" -> "Selma High".
    Runs of spaces collapse either way. A name that isn't entirely upper case
    was cased deliberately (McKinley, de Anza) and is left alone. The source
    names stay as imported; this is display only.
    """
    text = ' '.join(str(value or '').split())
    if not text or text != text.upper():
        return text
    return WORD_RE.sub(lambda match: match.group(0).capitalize(), text)


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


def _delta_phrase(delta, lead):
    """
    "Down 12% since 2022" (or lowercase when it isn't the first clause).
    None when the comparison can't be made. Anything under half a percent
    reads as unchanged rather than "up 0%".
    """
    if delta is None or delta['pct'] is None:
        return None
    pct = delta['pct']
    if abs(pct) < 0.5:
        phrase = f"Unchanged since {delta['year']}"
    else:
        word = 'Up' if pct > 0 else 'Down'
        phrase = f"{word} {int(round(abs(pct)))}% since {delta['year']}"
    return phrase if lead else phrase[0].lower() + phrase[1:]


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def trend_chart(by_year, year=None, hide_lbs=False, title=None):
    """
    The by-year trend: an inline SVG line chart and the delta sentence under
    it. Pounds, except on a placeholder chemical's page, which has none and
    charts its applications instead.
    """
    field = 'applications' if hide_lbs else 'lbs'
    metric_label = 'applications' if hide_lbs else 'pounds'
    width, height = 320, 90
    points = stats.trend_points(by_year, field, width=width, height=height)
    # Under All years no single point is the one being looked at, so nothing
    # is emphasised.
    selected = year
    deltas = stats.trend_deltas(by_year, year, field=field)
    previous = _delta_phrase(deltas['previous'], lead=True)
    first = _delta_phrase(deltas['first'], lead=previous is None)
    phrases = [phrase for phrase in (previous, first) if phrase]
    if phrases:
        sentence = ' · '.join(phrases)
    else:
        sentence = 'Only one year of data.' if len(points) == 1 else ''
    # Three values are written on the chart -- the first year, the last, and
    # the highest -- so the shape carries numbers without a hover.
    labelled = set()
    if points:
        values = [point[3] for point in points]
        peak = values.index(max(values))
        labelled = {0, len(points) - 1}
        # ...unless the peak sits near an end, where its label would run into
        # that end's.
        if width * 0.22 <= points[peak][0] <= width * 0.78:
            labelled.add(peak)
    return {
        'points': [
            {
                'x': x, 'y': y, 'year': point_year, 'value': value,
                'display': intcomma(value) if hide_lbs else lbs(value),
                'is_selected': point_year == selected,
                'label': (intcomma(value) if hide_lbs else lbs(value)) if index in labelled else '',
                # Keep the end labels inside the box, and off the point: the
                # first year's label starts just right of its point, the last
                # year's ends just left of its.
                'label_x': (x + 5) if index == 0 and len(points) > 1 else ((x - 5) if index == len(points) - 1 and len(points) > 1 else x),
                'label_y': max(round(y - 6, 1), 9),
                'anchor': 'start' if index == 0 and len(points) > 1 else ('end' if index == len(points) - 1 and len(points) > 1 else 'middle'),
                # The hover label sits under the point (above it near the baseline), pulled in at the ends.
                'hover_y': round(y + 14, 1) if y < height - 22 else round(y - 8, 1),
                'hover_anchor': 'start' if x < width * 0.15 else ('end' if x > width * 0.85 else 'middle'),
            }
            for index, (x, y, point_year, value) in enumerate(points)
        ],
        'polyline': ' '.join(f'{x},{y}' for x, y, _, _ in points),
        'sentence': sentence,
        'title': title or ('Applications by year' if hide_lbs else 'Lbs applied by year'),
        'metric_label': metric_label,
        'width': width,
        'height': height,
        'pad': 6,
        'baseline': height - 6,
        'first_year': points[0][2] if points else None,
        'last_year': points[-1][2] if points else None,
    }
