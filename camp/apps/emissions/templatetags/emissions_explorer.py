import uuid

from django import template
from django.utils.html import format_html

from camp.apps.emissions import dairies, sectors

register = template.Library()


@register.filter
def quantity(value):
    """
    A number already in its display unit, always to one decimal so a column
    of them lines up: '1,456.4', '214.0', '8.2', '<0.1', '0.0', '—'.
    """
    if value is None:
        return '—'
    value = float(value)
    if value and abs(value) < 0.05:
        return '<0.1'
    return f'{value:,.1f}'


@register.filter
def amount(tons, pollutant):
    """A pollutant amount (stored in tons) in its display unit; see quantity()."""
    return quantity(pollutant.display(tons))


@register.filter
def percent(share):
    if share is None:
        return '—'
    if 0 < share < 0.01:
        return '<1%'
    return f'{share * 100:.0f}%'


@register.filter
def width_pct(share):
    """A CSS width for a share bar."""
    return f'{(share or 0) * 100:.2f}%'


@register.filter
def signed_pct(pct):
    return f'+{pct:.0f}%' if pct >= 0 else f'−{abs(pct):.0f}%'


@register.simple_tag
def sector_description(sector):
    return sectors.sector_description(sector)


@register.simple_tag
def sic_title(sic):
    return sectors.sic_title(sic)


def _change_sentence(by_year, year):
    if year is None or year not in by_year or (year - 1) not in by_year or not by_year[year - 1]:
        return ''
    pct = (by_year[year] - by_year[year - 1]) / by_year[year - 1] * 100
    if abs(pct) < 0.5:
        return f'Unchanged from {year - 1}'
    return f"{'Up' if pct > 0 else 'Down'} {abs(pct):.0f}% from {year - 1}"


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def emissions_trend_chart(points, pollutant, year=None, title=None):
    """
    The by-year trend, drawn by js/pesticides/charts.js from the payload this
    embeds (same markup and chart type as the pesticides trend).
    """
    rows = sorted(points, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    values = [pollutant.display(row['value']) or 0 for row in rows]
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': pollutant.unit,
            'x': years,
            'y': values,
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': title or f'{pollutant.label} by year ({pollutant.unit}/yr)',
        'sentence': _change_sentence(dict(zip(years, values)), year),
        'first_year': years[0] if years else None,
        'last_year': years[-1] if years else None,
    }


@register.filter
def lookup(mapping, key):
    """mapping[key], or '' when there's no such key (or no mapping)."""
    try:
        return mapping.get(key, '')
    except AttributeError:
        return ''


@register.filter
def whole(value):
    """A head count or animal-unit total, rounded, with commas: '2,310'; '—' for none (a blank CADD count)."""
    if value is None or value == '':
        return '—'
    return f'{round(float(value)):,}'


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def dairy_trend_chart(points, year=None):
    """
    CADD's animal units (solid) and milk cows (dashed) by year, marked where
    CADD's coverage grew. The same markup as the emissions trend;
    js/pesticides/charts.js draws the second series and the marker.
    """
    rows = sorted(points, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    marker = None
    if years and years[0] < dairies.COVERAGE_CHANGE_YEAR <= years[-1]:
        marker = {'x': dairies.COVERAGE_CHANGE_YEAR, 'label': 'More dairies tracked'}
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': 'animal units',
            'x': years,
            'y': [round(row['animal_units']) for row in rows],
            'y2': [row['milk_cows'] for row in rows],
            'labels': ['animal units', 'milk cows'],
            'marker': marker,
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': 'Animal units (solid) and milk cows (dashed) by year',
        'sentence': '',
        'first_year': years[0] if years else None,
        'last_year': years[-1] if years else None,
    }


@register.simple_tag
def sparkline(points, width=100, height=24):
    """A tiny inline SVG trend line; '' with fewer than two points."""
    values = [row['value'] for row in sorted(points, key=lambda row: row['year'])]
    if len(values) < 2:
        return ''
    top = max(values) or 1
    step = width / (len(values) - 1)
    coords = ' '.join(
        f'{i * step:.1f},{height - 2 - (value / top) * (height - 4):.1f}'
        for i, value in enumerate(values)
    )
    return format_html(
        '<svg class="sparkline" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
        '<polyline points="{coords}"/></svg>',
        w=width, h=height, coords=coords,
    )
