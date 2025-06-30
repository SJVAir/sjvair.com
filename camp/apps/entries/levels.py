from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Union, List, Dict, Tuple

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
class Level:
    value: Union[float, Decimal]
    label: str
    color: str
    guidance: Optional[str] = None
    key: Optional[str] = None
    rank: int = 0

    def __repr__(self):
        return f'Level({self.value}, {self.label!r}, {self.color})'

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.rank >= other.rank

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.rank == other.rank


class AQLevelMeta(type):
    _levels = {
        'GOOD': {
            'label': _('Good'),
            'color': '#00ccff',
        },
        'MODERATE': {
            'label': _('Moderate'),
            'color': '#00e400',
            'guidance': _('Highly sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'UNHEALTHY_SENSITIVE': {
            'label': _('Unhealthy for Sensitive Groups'),
            'color': '#ffff00',
            'guidance': _('Sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'UNHEALTHY': {
            'label': _('Unhealthy'),
            'color': '#ff7e00',
            'guidance': _('Everyone should reduce prolonged or heavy exertion.'),
        },
        'VERY_UNHEALTHY': {
            'label': _('Very Unhealthy'),
            'color': '#ff0000',
            'guidance': _('Everyone should avoid prolonged or heavy exertion.'),
        },
        'HAZARDOUS': {
            'label': _('Hazardous'),
            'color': '#7e0023',
            'guidance': _('Everyone should stay indoors and avoid physical outdoor activities.'),
        },
        'VERY_HAZARDOUS': {
            'label': _('Very Hazardous'),
            'color': '#7e0023',
            'guidance': _('Everyone should stay indoors and avoid physical outdoor activities.'),
        },
    }

    def __getattr__(cls, key):
        if key not in cls._levels:
            raise AttributeError(f'{key} is not a valid AQ level')

        rank = list(cls._levels).index(key)
        meta = cls._levels[key]
        return lambda value, guidance=None: Level(
            key=key.lower(),
            label=meta['label'],
            value=value,
            rank=rank,
            color=meta['color'],
            guidance=guidance or meta.get('guidance'),
        )

class AQLevel(metaclass=AQLevelMeta):
    @classproperty
    def choices(cls):
        return [
            (key.lower(), meta['label'])
            for key, meta in cls._levels.items()
        ]

    @classproperty
    def scale(cls):
        if not hasattr(cls, '_scale'):
            cls._scale = LevelSet(*[
                getattr(cls, key)(i) for i, key in enumerate(cls._levels.keys())
            ])
        return cls._scale


class LevelSet:
    def __init__(self, *args: Level, **kwargs: Level):
        self._levels: List[Level] = []
        self._map: Dict[str, Level] = {}

        for idx, lvl in enumerate(args):
            key = (lvl.key or lvl.label.replace(' ', '_')).lower()
            if key in self._map:
                raise ValueError(f'Duplicate level key: {key}')
            object.__setattr__(lvl, 'key', key)
            self._levels.append(lvl)
            self._map[key.upper()] = lvl

        for idx, (attr, lvl) in enumerate(kwargs.items(), start=len(self._levels)):
            if attr in self._map:
                raise ValueError(f'Duplicate level key: {attr}')
            object.__setattr__(lvl, 'key', attr.lower())
            self._levels.append(lvl)
            self._map[attr] = lvl

    def __getattr__(self, attr: str) -> Level:
        try:
            return self._map[attr.upper()]
        except KeyError:
            raise AttributeError(f"No such level: {attr}")

    def __getitem__(self, key: str) -> Level:
        try:
            return self._map[key.upper()]
        except KeyError:
            raise KeyError(f"No such level: {key}")

    @property
    def choices(self) -> List[Tuple[str, str]]:
        return [(lvl.key.lower(), lvl.label) for lvl in self._levels]

    def get_level(self, value) -> Level:
        for lvl in reversed(self._levels):
            if value >= lvl.value:
                return lvl
        return self._levels[0]

    def get_color(self, value: Union[int, float]) -> str:
        levels = sorted(self._levels, key=lambda l: l.value)
        for i, level in enumerate(levels):
            min_val = level.value
            max_val = levels[i + 1].value if i + 1 < len(levels) else float('inf')
            if min_val <= value < max_val:
                ratio = (value - min_val) / (max_val - min_val) if max_val != float('inf') else 0
                return _blend_hex(level.color, levels[i + 1].color if i + 1 < len(levels) else level.color, ratio)
        return levels[0].color

    def lookup(self, key: str) -> Level:
        return self._map[key.upper()]

    def as_dict(self) -> Dict[str, Dict[str, any]]:
        result = {}
        levels = sorted(self._levels, key=lambda l: l.value)
        for i, level in enumerate(levels):
            max_value = (levels[i + 1].value - 0.1) if i + 1 < len(levels) else 99999
            result[level.key.upper()] = {
                'name': level.key,
                'label': level.label,
                'color': level.color,
                'range': (level.value, max_value),
                'guidance': level.guidance,
            }
        return result
