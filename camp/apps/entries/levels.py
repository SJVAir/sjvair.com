from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union, List, Dict, Tuple

from django.utils.translation import gettext_lazy as _

from camp.utils import classproperty
from camp.utils.scales import Scale, ScaleLevel

EPA_SOURCE = {
    'name': 'US EPA AirNow, AQI Basics',
    'url': 'https://www.airnow.gov/aqi/aqi-basics/',
}


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
    tier: Optional[int] = None
    description: str = ''

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
            'color': '#00e400',
            'tier': 0,
            'description': _('Air quality is satisfactory, and air pollution poses little or no risk.'),
        },
        'MODERATE': {
            'label': _('Moderate'),
            'color': '#ffff00',
            'tier': 1,
            'description': _('Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.'),
            'guidance': _('Highly sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'UNHEALTHY_SENSITIVE': {
            'label': _('Unhealthy for Sensitive Groups'),
            'color': '#ff7e00',
            'tier': 2,
            'description': _('Members of sensitive groups may experience health effects. The general public is less likely to be affected.'),
            'guidance': _('Sensitive groups should stay indoors and avoid outdoor activities.'),
        },
        'UNHEALTHY': {
            'label': _('Unhealthy'),
            'color': '#ff0000',
            'tier': 3,
            'description': _('Some members of the general public may experience health effects; members of sensitive groups may experience more serious health effects.'),
            'guidance': _('Everyone should reduce prolonged or heavy exertion.'),
        },
        'VERY_UNHEALTHY': {
            'label': _('Very Unhealthy'),
            'color': '#8f3f97',
            'tier': 4,
            'description': _('Health alert: The risk of health effects is increased for everyone.'),
            'guidance': _('Everyone should avoid prolonged or heavy exertion.'),
        },
        'HAZARDOUS': {
            'label': _('Hazardous'),
            'color': '#7e0023',
            'tier': 4,
            'description': _('Health warning of emergency conditions: everyone is more likely to be affected.'),
            'guidance': _('Everyone should stay indoors and avoid physical outdoor activities.'),
        },
        'VERY_HAZARDOUS': {
            'label': _('Very Hazardous'),
            'color': '#7e0023',
            'tier': 4,
            'description': _('Health warning of emergency conditions: everyone is more likely to be affected.'),
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
            tier=meta['tier'],
            description=meta['description'],
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

    def __iter__(self):
        return iter(self._levels)

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

    def to_scale(self, id: str, label: str, units: str) -> Scale:
        levels = sorted(self._levels, key=lambda l: l.value)
        return Scale(
            id=id,
            label=label,
            units=units,
            kind='range',
            source=EPA_SOURCE,
            levels=tuple(
                ScaleLevel(
                    key=level.key,
                    label=level.label,
                    color=level.color,
                    tier=level.tier,
                    description=level.description,
                    guidance=level.guidance or '',
                    min=level.value,
                    max=levels[i + 1].value if i + 1 < len(levels) else None,
                )
                for i, level in enumerate(levels)
            ),
        )


# Pollutant-specific level sets, breakpoints in each pollutant's native unit.
# Import this module (not these names directly) to avoid colliding with the
# identically-named entry models in camp.apps.entries.models, e.g.:
#     from . import levels
#     Levels = levels.PM25

PM25 = LevelSet(
    AQLevel.GOOD(0.0),
    AQLevel.MODERATE(9.1),
    AQLevel.UNHEALTHY_SENSITIVE(35.5),
    AQLevel.UNHEALTHY(55.5),
    AQLevel.VERY_UNHEALTHY(125.5),
    AQLevel.HAZARDOUS(225.5),
)

PM100 = LevelSet(
    AQLevel.GOOD(0),
    AQLevel.MODERATE(55),
    AQLevel.UNHEALTHY_SENSITIVE(155),
    AQLevel.UNHEALTHY(255),
    AQLevel.VERY_UNHEALTHY(355),
    AQLevel.HAZARDOUS(425),
    AQLevel.VERY_HAZARDOUS(605),
)

CO = LevelSet(
    AQLevel.GOOD(0.0),
    AQLevel.MODERATE(4.5),
    AQLevel.UNHEALTHY_SENSITIVE(9.5),
    AQLevel.UNHEALTHY(12.5),
    AQLevel.VERY_UNHEALTHY(15.5),
    AQLevel.HAZARDOUS(30.5),
    AQLevel.VERY_HAZARDOUS(50.4),
)

NO2 = LevelSet(
    AQLevel.GOOD(0.0),
    AQLevel.MODERATE(54.0),
    AQLevel.UNHEALTHY_SENSITIVE(101.0),
    AQLevel.UNHEALTHY(361.0),
    AQLevel.VERY_UNHEALTHY(650.0),
    AQLevel.HAZARDOUS(1250.0),
    AQLevel.VERY_HAZARDOUS(2050.0),
)

O3 = LevelSet(
    AQLevel.GOOD(0.0),
    AQLevel.UNHEALTHY_SENSITIVE(125),
    AQLevel.UNHEALTHY(165),
    AQLevel.VERY_UNHEALTHY(205),
    AQLevel.HAZARDOUS(405),
    AQLevel.VERY_HAZARDOUS(605),
)

SO2 = LevelSet(
    AQLevel.GOOD(0),
    AQLevel.MODERATE(36),
    AQLevel.UNHEALTHY_SENSITIVE(76),
    AQLevel.UNHEALTHY(186),
    AQLevel.VERY_UNHEALTHY(305),
)

# The EPA Air Quality Index itself (0-500), as opposed to a pollutant's raw
# concentration. Breakpoints match camp.utils.aqi.aqi_label exactly (301+ is
# "Hazardous" all the way to 500 -- the EPA AQI has no tier past Hazardous).
AQI = LevelSet(
    AQLevel.GOOD(0),
    AQLevel.MODERATE(51),
    AQLevel.UNHEALTHY_SENSITIVE(101),
    AQLevel.UNHEALTHY(151),
    AQLevel.VERY_UNHEALTHY(201),
    AQLevel.HAZARDOUS(301),
)
