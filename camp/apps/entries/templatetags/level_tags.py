from decimal import Decimal

from django import template

register = template.Library()

# Bulma's $text: dark text keeps the contrast the old Sass tags had on light levels.
DARK_TEXT = '#363636'
LIGHT_TEXT = '#fff'


@register.filter
def level_style(level):
    """Inline background and text color for a level, e.g. on a tag or table header."""
    if level is None:
        return ''
    text = LIGHT_TEXT if (level.tier or 0) >= 2 else DARK_TEXT
    return f'background-color: {level.color}; color: {text}'


@register.filter
def level_range(levelset, decimals):
    """Each level's range as text ("9.1 – 35.4"), the top one open-ended ("≥225.5")."""
    decimals = int(decimals)
    step = Decimal(1).scaleb(-decimals)
    mins = [Decimal(str(level.value)) for level in sorted(levelset, key=lambda l: l.value)]
    fmt = f'{{:.{decimals}f}}'
    ranges = [
        f'{fmt.format(low)} – {fmt.format(high - step)}'
        for low, high in zip(mins, mins[1:])
    ]
    ranges.append(f'≥{fmt.format(mins[-1])}')
    return ranges
