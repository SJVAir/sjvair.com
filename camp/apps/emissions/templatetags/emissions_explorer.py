import uuid

from django import template
from django.urls import reverse
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
def share_pct(value):
    """
    A share of the Valley total (0-1) as a percent with the precision small
    shares need: '24%', '1.2%', '0.03%', '<0.01%', '0%', '—'.
    """
    if value is None:
        return '—'
    value = float(value)
    if value == 0:
        return '0%'
    pct = value * 100
    if pct < 0.01:
        return '<0.01%'
    if pct < 0.1:
        return f'{pct:.2f}%'
    if pct < 10:
        return f'{pct:.1f}%'
    return f'{pct:.0f}%'


@register.filter
def amount(value, pollutant):
    """A pollutant amount (already in its display unit) formatted: a percent for a weighted measure, else quantity()."""
    if pollutant.unit == 'share':
        return share_pct(pollutant.display(value))
    return quantity(pollutant.display(value))


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
    unit = pollutant.unit
    if unit == 'share':
        values = [value * 100 for value in values]
        unit = '%'
    default_title = (
        f'{pollutant.label} toxics, share of Valley total by year (%)' if unit == '%'
        else f'{pollutant.label} by year ({unit}/yr)'
    )
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': unit,
            'x': years,
            'y': values,
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': title or default_title,
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


@register.simple_tag(takes_context=True)
def dairy_city(context, dairy):
    """A dairy's mailing city, linked to the city's (or CDP's) dairy page when it has one; the text is the city as stored."""
    city = (dairy.address or {}).get('city') or ''
    url = dairies.city_url(city)
    if not url:
        return city
    return format_html('<a href="{}{}">{}</a>', url, context.get('region_qs', ''), city)


@register.filter
def whole(value):
    """A head count, rounded, with commas: '2,310'; '—' for none (a blank CADD count)."""
    if value is None or value == '':
        return '—'
    return f'{round(float(value)):,}'


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def dairy_trend_chart(points, year=None):
    """
    CADD's mature dairy cows (solid) and other cattle (dashed) by year, marked where
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
            'unit': 'head',
            'x': years,
            'y': [row['mature_cows'] for row in rows],
            'y2': [row['other_cattle'] for row in rows],
            'labels': ['mature dairy cows', 'other cattle'],
            'marker': marker,
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': 'Mature dairy cows (solid) and other cattle (dashed) by year',
        'sentence': '',
        'first_year': years[0] if years else None,
        'last_year': years[-1] if years else None,
    }


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def dairy_emissions_chart(points, pollutant, year=None, place=None):
    """
    CARB's dairy cattle emissions by year (dairies.emissions_trend), the
    readout adding each year's share of `place`'s all-sources total (the
    covered counties when there's no place). Nothing for a pollutant CARB
    doesn't report for dairy cattle: emissions_trend is [] for those.
    """
    rows = sorted(points, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    place = place or 'the covered counties'
    since = dairies.flat_since(rows)
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': 'tons',
            'x': years,
            'y': [row['value'] for row in rows],
            'notes': [
                f"{percent(row['share'])} of {place} {pollutant.label}" if row['share'] is not None else ''
                for row in rows
            ],
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': f'Dairy cattle {pollutant.label}, CARB estimate',
        'sentence': '',
        'note': 'Animals and manure only: CARB counts feed and silage, dairies’ larger ROG source, separately. Years after 2017 are CARB projections'
        + (f'; its estimate is the same every year since {since}.' if since else '.'),
        'note_url': reverse('emissions:about') + '#dairies',
        'first_year': years[0] if years else None,
        'last_year': years[-1] if years else None,
    }


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def digester_trend_chart(points, year=None):
    """Counted dairies with an operating digester by year (dairies.digester_trend); nothing when no year has one."""
    rows = sorted(points, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': 'dairies',
            'whole': True,
            'x': years,
            'y': [row['digesters'] for row in rows],
            'labels': ['dairies with a digester'],
            'selected': year if year in years else None,
        },
        'has_data': any(row['digesters'] for row in rows),
        'title': 'Dairies with an operating digester',
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
