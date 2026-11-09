from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class ScaleLevel:
    key: str
    label: str
    color: str | None
    tier: int | None
    description: str = ''
    guidance: str = ''
    min: float | None = None
    max: float | None = None
    value: str | int | None = None
    opacity: float | None = None


@dataclass(frozen=True)
class Scale:
    id: str
    label: str
    units: str
    kind: Literal['range', 'category']
    levels: tuple[ScaleLevel, ...]
    source: dict | None = None
    averaging_hours: int | None = None
    daily_statistic: str | None = None
    daily_statistic_label: str | None = None

    def to_json(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'units': self.units,
            'kind': self.kind,
            'source': self.source,
            'averaging_hours': self.averaging_hours,
            'daily_statistic': self.daily_statistic,
            'daily_statistic_label': None if self.daily_statistic_label is None else str(self.daily_statistic_label),
            'levels': [asdict(level) for level in self.levels],
        }
