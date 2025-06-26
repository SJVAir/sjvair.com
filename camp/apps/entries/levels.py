import enum

from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from camp.utils import classproperty


def _blend_hex(hex1, hex2, ratio):
    """Blend two hex colors. Ratio is from 0 (hex1) to 1 (hex2)."""
    def hex_to_rgb(h):
        h = h.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(*rgb)

    rgb1 = hex_to_rgb(hex1)
    rgb2 = hex_to_rgb(hex2)

    blended = tuple(
        int(round(a + (b - a) * ratio)) for a, b in zip(rgb1, rgb2)
    )
    return rgb_to_hex(blended)


@dataclass(frozen=True, slots=True)
class Lvl:
    value: [float, Decimal]
    label: str
    color: str
    guidance: [None, str] = None

    def __repr__(self):
        return f'Lvl({self.value}, {self.label!r}, {self.color})'


# Shortcut for common EPA Air Quality Levels.

class AQLvlMeta(type):
    _levels = {
        'VERY_HAZARDOUS': {
            'label': _('Very Hazardous'),
            'color': '#7e0023',
            'guidance': _('Everyone should stay indoors and avoid physical outdoor activities.'),
        },
        'HAZARDOUS': {
            'label': _('Hazardous'),
            'color': '#7e0023',
            'guidance': _('Everyone should stay indoors and avoid physical outdoor activities.'),
        },
        'VERY_UNHEALTHY': {
            'label': _('Very Unhealthy'),
            'color': '#ff0000',
            'guidance': _('Everyone should avoid prolonged or heavy exertion.'),
        },
        'UNHEALTHY': {
            'label': _('Unhealthy'),
            'color': '#ff7e00',
            'guidance': _('Everyone should reduce prolonged or heavy exertion.'),
        },
        'UNHEALTHY_SENSITIVE': {
            'label': _('Unhealthy for Sensitive Groups'),
            'color': '#ffff00',
            'guidance': _('Sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'MODERATE': {
            'label': _('Moderate'),
            'color': '#00e400',
            'guidance': _('Highly sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'GOOD': {
            'label': _('Good'),
            'color': '#00ccff',
        },
    }

    def __getattr__(self, name):
        if name not in self._levels:
            raise AttributeError(f'{name} is not a valid AQ level')

        meta = self._levels[name]
        return lambda value, guidance=None: (
            name,
            Lvl(
                value=value,
                label=meta['label'],
                color=meta['color'],
                guidance=guidance or meta.get('guidance')
            )
        )


class AQLvl(metaclass=AQLvlMeta):
    @classproperty
    def choices(cls):
        return [
            (key.lower(), meta['label'])
            for key, meta in cls._levels.items()
        ]


class PollutantLevels(enum.Enum):
    def __init__(self, lvl: Lvl):
        self._lvl = lvl

    @property
    def value(self):
        return self._lvl.value

    @property
    def key(self):
        return self.name.lower()

    def __getattr__(self, name):
        if name in ('_value_', '_lvl', 'value'):
            raise AttributeError(f'{name} is not accessible')
        return getattr(self._lvl, name)

    @classproperty
    def choices(cls):
        return [(l.key, l.label) for l in cls]

    @classmethod
    def get_level(cls, value):
        levels = sorted(cls, key=lambda l: l.value, reverse=True)
        for level in levels:
            if value >= level.value:
                return level
        return levels[-1]

    @classmethod
    def get_color(cls, value):
        levels = sorted(cls, key=lambda l: l.value)
        for i, level in enumerate(levels):
            min_val = level.value
            max_val = levels[i + 1].value if i + 1 < len(levels) else float('inf')

            if min_val <= value < max_val:
                ratio = (value - min_val) / (max_val - min_val) if max_val != float('inf') else 0
                return _blend_hex(level.color, levels[i + 1].color if i + 1 < len(levels) else level.color, ratio)

        return levels[0].color

    @classmethod
    def lookup(cls, key):
        key = key.lower()
        for lvl in cls:
            if lvl.key == key:
                return lvl

    @classmethod
    def as_dict(cls):
        levels = sorted(cls, key=lambda l: l.value)
        result = {}

        for i, level in enumerate(levels):
            max_value = (levels[i + 1].value - 0.1) if i + 1 < len(levels) else 99999

            result[level.name] = {
                'name': level.name,
                'label': level.label,
                'color': level.color,
                'range': (level.value, max_value),
                'guidance': level.guidance,
            }

        return result

    @classmethod
    def from_aq_levels(cls, *levels: tuple[str, Lvl]):
        return PollutantLevels('AQLevels', names=levels)
