from camp.utils.scales import Scale, ScaleLevel

from .models import Smoke

SOURCE = {
    'name': 'NOAA Hazard Mapping System',
    'url': 'https://www.ospo.noaa.gov/products/land/hms.html',
}

# (density, color, fill opacity, tier)
_SMOKE = [
    (Smoke.Density.LIGHT, '#bfc8c3', 0.2, 1),
    (Smoke.Density.MEDIUM, '#757b78', 0.3, 2),
    (Smoke.Density.HEAVY, '#333634', 0.4, 3),
]

# (key, label, min, max, color); half-open: min <= value < max
_FIRE = [
    ('sm', '<10', 0, 10, '#FFD700'),
    ('md', '10–49', 10, 50, '#FF8C00'),
    ('lg', '50–149', 50, 150, '#FF4500'),
    ('xl', '150–349', 150, 350, '#DC143C'),
    ('xxl', '≥350', 350, None, '#8B0000'),
]


def get_smoke_scale():
    return Scale(
        id='smoke-density',
        label='Smoke density',
        units='',
        kind='category',
        source=SOURCE,
        levels=tuple(
            ScaleLevel(
                key=density.value,
                label=density.label,
                color=color,
                tier=tier,
                value=density.value,
                opacity=opacity,
            )
            for density, color, opacity, tier in _SMOKE
        ),
    )


def get_fire_scale():
    return Scale(
        id='fire-frp',
        label='Fire radiative power',
        units='MW',
        kind='range',
        source=SOURCE,
        levels=tuple(
            ScaleLevel(key=key, label=label, color=color, tier=None, min=low, max=high)
            for key, label, low, high, color in _FIRE
        ),
    )
