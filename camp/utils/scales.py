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

    def to_json(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'units': self.units,
            'kind': self.kind,
            'source': self.source,
            'levels': [asdict(level) for level in self.levels],
        }
