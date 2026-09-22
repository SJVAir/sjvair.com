"""
Server-rendered SVG charts for admin pages. Pure Python, no JavaScript:
the admin has no chart library and these pages are read, not explored.
"""

import math
from datetime import date, timedelta
from html import escape

from django.utils.safestring import mark_safe

MARGIN = {'top': 12, 'right': 16, 'bottom': 28, 'left': 44}


def nice_ceiling(value):
    """Round a positive number up to 1, 2, 2.5 or 5 times a power of ten."""
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * base:
            return step * base
    return 10 * base


def x_ticks(first, last):
    """Tick dates: every 7 days for ranges under 60 days, otherwise month starts (plus the first day)."""
    span = (last - first).days
    if span < 60:
        return [first + timedelta(days=i) for i in range(0, span + 1, 7)]
    ticks = [first]
    year, month = first.year, first.month
    while True:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        tick = date(year, month, 1)
        if tick > last:
            break
        ticks.append(tick)
    return ticks


def line_chart(series, bands=(), width=720, height=240, y_label=''):
    points = [point for item in series for point in item['points']]
    dates = [d for d, _v in points]
    values = [v for _d, v in points if v is not None]

    inner_w = width - MARGIN['left'] - MARGIN['right']
    inner_h = height - MARGIN['top'] - MARGIN['bottom']
    first, last = (min(dates), max(dates)) if dates else (date.today(), date.today())
    span_days = max((last - first).days, 1)

    y_max = nice_ceiling(max(values) * 1.1) if values else 1.0
    # Show at least the first non-zero band so the scale reads the same across regions.
    first_band = next((minimum for minimum, _c in bands if minimum > 0), None)
    if first_band is not None and y_max < first_band * 1.2:
        y_max = nice_ceiling(first_band * 1.2)

    def sx(d):
        return MARGIN['left'] + (d - first).days / span_days * inner_w

    def sy(v):
        return MARGIN['top'] + inner_h - (min(v, y_max) / y_max) * inner_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">']

    for index, (minimum, color) in enumerate(bands):
        if minimum >= y_max:
            break
        top = bands[index + 1][0] if index + 1 < len(bands) else y_max
        top = min(top, y_max)
        parts.append(
            f'<rect class="chart-band" x="{MARGIN["left"]}" y="{sy(top):.1f}" width="{inner_w}" '
            f'height="{sy(minimum) - sy(top):.1f}" fill="{escape(color)}" fill-opacity="0.12"/>'
        )

    # Axes and ticks
    parts.append(f'<line class="chart-axis" x1="{MARGIN["left"]}" y1="{MARGIN["top"] + inner_h}" x2="{width - MARGIN["right"]}" y2="{MARGIN["top"] + inner_h}" stroke="#999"/>')
    parts.append(f'<line class="chart-axis" x1="{MARGIN["left"]}" y1="{MARGIN["top"]}" x2="{MARGIN["left"]}" y2="{MARGIN["top"] + inner_h}" stroke="#999"/>')
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        value = y_max * fraction
        label = f'{value:g}'
        parts.append(f'<text x="{MARGIN["left"] - 6}" y="{sy(value) + 4:.1f}" text-anchor="end" font-size="11" fill="#666" class="chart-ytick">{label}</text>')
    if dates:
        for tick in x_ticks(first, last):
            label = tick.strftime('%b %-d') if span_days < 60 else tick.strftime('%b')
            parts.append(f'<text class="chart-xtick" x="{sx(tick):.1f}" y="{height - 8}" text-anchor="middle" font-size="11" fill="#666">{label}</text>')
    if y_label:
        parts.append(f'<text class="chart-ylabel" x="{MARGIN["left"]}" y="{MARGIN["top"] - 2}" font-size="11" fill="#666">{escape(y_label)}</text>')

    for item in series:
        segments, current = [], []
        for d, v in item['points']:
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append((sx(d), sy(v)))
        if current:
            segments.append(current)
        dash = ' stroke-dasharray="6 4"' if item.get('dashed') else ''
        color = escape(item['color'])
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0]
                parts.append(f'<circle class="chart-point" cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
                continue
            d_attr = ' '.join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in enumerate(segment))
            parts.append(f'<path class="chart-line" d="{d_attr}" fill="none" stroke="{color}" stroke-width="2"{dash}><title>{escape(item["label"])}</title></path>')

    parts.append('</svg>')
    return mark_safe(''.join(parts))
