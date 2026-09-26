import calendar
import math
import re
import uuid

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


# Columns whose natural first click is A-Z rather than largest-first.
TEXT_SORT_KEYS = ('name', 'city', 'type')


@register.simple_tag(takes_context=True)
def sort_link(context, key, label, param='sort'):
    """
    Column header link. Clicking the active column flips direction; clicking
    another column sorts descending for numeric-style keys ('lbs', counts) and
    ascending for text ones. Always resets `page`.

    `param` is the query-string key the sort lives under, and the context key
    the current sort is read from -- a table with its own sort state on a page
    that already has one (the district page's schools table) prefixes it.
    """
    current = context.get(param) or ''
    active = current.lstrip('-') == key
    descending = current.startswith('-')
    if active:
        target = key if descending else f'-{key}'
        icon = 'fa-arrow-down-wide-short' if descending else 'fa-arrow-up-short-wide'
    else:
        target = key if key in TEXT_SORT_KEYS else f'-{key}'
        icon = 'fa-arrow-up-arrow-down'
    href = qs_replace(context, page=None, **{param: target})
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
def signed_lbs(value):
    """
    `lbs` with the sign always shown, for a change. An increase reads "+400"
    rather than "400", so the direction never rests on the colour of a map
    swatch or the column a row happens to be in.
    """
    if value is None:
        return '—'
    if not value:
        return '0'
    return f'+{lbs(value)}' if value > 0 else lbs(value)


@register.filter
def signed_pct(value):
    """A percent change, signed, to one decimal. Blank for None -- top_movers
    leaves it off where the baseline is too small to mean anything."""
    if value is None:
        return ''
    return f'{value:+.1f}%'


# A word, with an apostrophe inside it kept ("CHILDREN'S" -> "Children's").
# Letters rather than [A-Za-z] so an accented name ("CANADA" with a tilde)
# doesn't come back out half-shouted.
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


# Tokens a source shouts that should stay shouted: district and agency
# initialisms, and roman numerals ("SITE III").
NAME_ACRONYMS = {
    'USD', 'EOC', 'YMCA', 'YWCA', 'CDC', 'CDCC', 'CCC', 'LLC', 'INC', 'KCAO', 'CSU', 'CSUF', 'UC', 'UCSF',
    'SJV', 'CA', 'PS', 'HS', 'JHS', 'MS', 'ES', 'MLK', 'JFK', 'ABC', 'HSA', 'ROP', 'STEM', 'STEAM', 'TK',
}
NAME_ACRONYM_RE = re.compile(r'^(?:[A-Z]{1,5}USD|[IVX]{2,4})$')


def _case_word(word):
    upper = word.upper()
    if upper in NAME_ACRONYMS or NAME_ACRONYM_RE.match(upper):
        return upper
    return word[:1].upper() + word[1:].lower()


@register.filter
def title_case_name(value):
    """
    A shouted source name as a readable one: "SELMA  HIGH" -> "Selma High",
    "FUSD-STOREY" -> "FUSD-Storey", "CAMPUS CENTER - SITE III" keeps its
    numeral, "LEARNING EXPERIENCE THE" -> "The Learning Experience". Runs of
    spaces collapse either way. A name that isn't entirely upper case was
    cased deliberately (McKinley, de Anza) and is left alone. The source names
    stay as imported; this is display only.
    """
    text = ' '.join(str(value or '').split())
    if not text or text != text.upper():
        return text
    # A listing-style trailing article ("... THE", "... A") goes back to the front.
    parts = text.split(' ')
    if len(parts) > 1 and parts[-1] in ('THE', 'A', 'AN'):
        parts = [parts[-1]] + parts[:-1]
    text = ' '.join(parts)
    return WORD_RE.sub(lambda match: _case_word(match.group(0)), text)


@register.filter
def month_abbr(value):
    return calendar.month_abbr[value]


@register.filter
def month_name(value):
    return calendar.month_name[value]


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


def _chart_id():
    return f'chart-{uuid.uuid4().hex[:8]}'


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def trend_chart(by_year, year=None, hide_lbs=False, title=None, compare=None, compare_label=''):
    """
    The by-year trend: a uPlot line drawn in the browser from the data this
    tag embeds (see assets/js/pesticides/charts.js), with the delta sentence
    under it rendered here. Pounds, except on a placeholder chemical's page,
    which has none and charts its applications instead.

    `compare` is an optional second by-year series -- the average valley
    county, on a county's page -- drawn dashed behind the first so the line
    can be read against something. It's aligned to the years the main series
    has, with a gap for any year it doesn't cover, rather than stretched to
    fit; a baseline that invented values would be worse than no baseline.
    """
    field = 'applications' if hide_lbs else 'lbs'
    metric_label = 'applications' if hide_lbs else 'pounds'
    rows = sorted(by_year, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    values = [row[field] or 0 for row in rows]
    deltas = stats.trend_deltas(by_year, year, field=field)
    previous = _delta_phrase(deltas['previous'], lead=True)
    first = _delta_phrase(deltas['first'], lead=previous is None)
    phrases = [phrase for phrase in (previous, first) if phrase]
    if phrases:
        sentence = ' · '.join(phrases)
    else:
        sentence = 'Only one year of data.' if len(rows) == 1 else ''
    title = title or ('Applications by year' if hide_lbs else 'Lbs applied by year')
    first_year = years[0] if years else None
    last_year = years[-1] if years else None
    baseline = {row['year']: row[field] or 0 for row in (compare or [])}
    return {
        'chart_id': _chart_id(),
        'chart': {
            'type': 'line',
            'unit': metric_label,
            'x': years,
            'y': values,
            'compare': [baseline.get(y) for y in years] if baseline else None,
            'compare_label': compare_label,
            # Under All years no single point is the one being looked at, so
            # nothing is emphasised.
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': title,
        'metric_label': metric_label,
        'compare_label': compare_label if baseline else '',
        'sentence': sentence,
        'first_year': first_year,
        'last_year': last_year,
    }


@register.inclusion_tag('pesticides/includes/month-chart.html')
def month_chart(by_month, year_label=None):
    """
    The by-month bars for a place or section, one bar per month of the scope
    year (or of every year, summed), drawn in the browser from the embedded
    data. Pounds on the bars; applications ride along for the hover readout.
    """
    rows = sorted(by_month, key=lambda row: row['month'])
    return {
        'chart_id': _chart_id(),
        'chart': {
            'type': 'bars',
            'unit': 'pounds',
            'labels': [calendar.month_abbr[row['month']] for row in rows],
            'names': [calendar.month_name[row['month']] for row in rows],
            'x': list(range(len(rows))),
            'y': [row['lbs'] or 0 for row in rows],
            'applications': [row.get('applications') or 0 for row in rows],
        },
        'rows': rows,
        'year_label': year_label,
    }


# The seasonality heatmap's scale: five steps sampled from the county map's
# default ramp, so a heavy month and a heavy county look the same shade.
HEATMAP_CLASSES = 5


def _heatmap_colors():
    from camp.apps.pesticides import maps
    return maps.sample_ramp(maps.RAMP, HEATMAP_CLASSES), maps.NO_DATA


def _heatmap_class(value, top):
    """
    Which of HEATMAP_CLASSES a cell falls in, linear on the heaviest cell in
    the grid. Linear rather than quantiled on purpose: use really is packed
    into two or three months, and quantiling the cells would spread that
    across the whole ramp and paint a flat year as a seasonal one. The cost is
    that a light month sits in the palest class -- which is the truth.
    """
    if not value or not top:
        return None
    step = math.ceil(value / top * HEATMAP_CLASSES)
    return min(HEATMAP_CLASSES, max(1, step)) - 1


@register.inclusion_tag('pesticides/includes/month-heatmap.html')
def month_heatmap(grid, year=None):
    """
    Months across, years down, each cell shaded by pounds: the seasonal shape
    of the use and whether it has moved. `grid` is stats.by_year_month().

    A single year renders nothing -- there is no shift to see, and the by-month
    bars already say everything one row could.
    """
    rows = list(grid or [])
    colors, no_data = _heatmap_colors()
    top = max((cell['lbs'] for row in rows for cell in row['months']), default=0)
    if len(rows) < 2 or not top:
        return {'has_data': False}

    def cell(row, entry):
        index = _heatmap_class(entry['lbs'], top)
        return {
            'lbs': entry['lbs'],
            'color': no_data if index is None else colors[index],
            'label': f"{calendar.month_name[entry['month']]} {row['year']}",
            'empty': index is None,
        }

    return {
        'has_data': True,
        'months': [calendar.month_abbr[month] for month in range(1, 13)],
        'rows': [
            {
                'year': row['year'],
                'lbs': row['lbs'],
                'selected': row['year'] == year,
                'cells': [cell(row, entry) for entry in row['months']],
            }
            for row in rows
        ],
        # Palest to darkest, for the legend under the grid.
        'scale': colors,
        'top': top,
    }


# A leaderboard sparkline: wide enough to read a shape, short enough to sit
# on one table row. Drawn as inline SVG rather than through charts.js --
# forty uPlot instances on the landing page to draw forty static 64x18
# polylines is a lot of canvas for a picture nobody interacts with.
SPARK_WIDTH = 64
SPARK_HEIGHT = 18
SPARK_PAD = 2


@register.filter
def sparkline(values):
    """
    `values` (a by-year series) as an inline SVG polyline, scaled to its own
    maximum so the shape is readable whatever the magnitude -- these say
    "rising" or "receding", never "bigger than the row below".

    Stays aria-hidden and unlabelled: the row already reads as its name and
    its pounds, and what the line covers is said once under the board
    (stats.series_label) rather than five times over. Keeping it out of here also
    keeps this a pure formatting filter with no database behind it.

    Empty, single-point and flat-zero series render nothing: a line needs two
    points to have a shape, and a flat line at zero would read as a real
    measurement of nothing.
    """
    series = [float(v or 0) for v in (values or [])]
    if len(series) < 2 or not any(series):
        return ''
    top = max(series)
    span = len(series) - 1
    inner_w = SPARK_WIDTH - 2 * SPARK_PAD
    inner_h = SPARK_HEIGHT - 2 * SPARK_PAD
    points = ' '.join(
        '%.1f,%.1f' % (
            SPARK_PAD + inner_w * i / span,
            SPARK_PAD + inner_h * (1 - (value / top)),
        )
        for i, value in enumerate(series)
    )
    return format_html(
        '<svg class="sparkline" viewBox="0 0 {} {}" width="{}" height="{}" '
        'preserveAspectRatio="none" aria-hidden="true" focusable="false">'
        '<polyline points="{}" fill="none" stroke="currentColor" '
        'stroke-width="1.25" stroke-linejoin="round" stroke-linecap="round"/></svg>',
        SPARK_WIDTH, SPARK_HEIGHT, SPARK_WIDTH, SPARK_HEIGHT, points,
    )
