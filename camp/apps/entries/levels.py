import enum

from dataclasses import dataclass

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
    value: float
    label: str
    color: str

    def __repr__(self):
        return f'Lvl({self.value}, {self.label!r}, {self.color})'


# Shortcut for common EPA Air Quality Levels.

class AQLvlMeta(type):
    _levels = {
        'VERY_HAZARDOUS': ('Very Hazardous', '#7e0023'),
        'HAZARDOUS': ('Hazardous', '#7e0023'),
        'VERY_UNHEALTHY': ('Very Unhealthy', '#ff0000'),
        'UNHEALTHY': ('Unhealthy', '#ff7e00'),
        'UNHEALTHY_SENSITIVE': ('Unhealthy for Sensitive Groups', '#ffff00'),
        'MODERATE': ('Moderate', '#00e400'),
        'GOOD': ('Good', '#00ccff'),
    }

    def __getattr__(self, name):
        if name not in self._levels:
            raise AttributeError(f'{name} is not a valid AQ level')

        label, color = self._levels[name]
        return lambda value: (name, Lvl(value, label, color))


class AQLvl(metaclass=AQLvlMeta):
    pass


class PollutantLevels(enum.Enum):
    def __init__(self, lvl: Lvl):
        self._lvl = lvl

    @property
    def value(self):
        return self._lvl.value

    def __getattr__(self, name):
        if name in ('_value_', '_lvl', 'value'):
            raise AttributeError(f'{name} is not accessible')
        return getattr(self._lvl, name)

    @classproperty
    def choices(cls):
        return [(l.name, l.label) for l in cls]

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
    def as_dict(cls, include_range=True):
        levels = sorted(cls, key=lambda l: l.value)
        result = {}

        for i, level in enumerate(levels):
            max_value = (levels[i + 1].value - 0.1) if i + 1 < len(levels) else 99999

            result[level.name] = {
                'name': level.name,
                'label': level.label,
                'color': level.color,
                'range': (level.value, max_value)
            }

        return result

    @classmethod
    def from_aq_levels(cls, *levels: tuple[str, Lvl]):
        return PollutantLevels('AQLevels', names=levels)
