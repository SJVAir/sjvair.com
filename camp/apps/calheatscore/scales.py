from camp.utils.scales import Scale, ScaleLevel

from .models import CalHeatScore

SOURCE = {
    'name': 'CalHeatScore (CalEPA / OEHHA)',
    'url': 'https://calheatscore.calepa.ca.gov/',
}

# (key, score, color, description, guidance)
_LEVELS = [
    (
        'low', CalHeatScore.Score.LOW, '#dedede',
        'Little to no heat-related health impacts are expected.',
        '',
    ),
    (
        'mild', CalHeatScore.Score.MILD, '#fae0c8',
        'Warm day. A minor increase in heat-related health impacts is expected among those sensitive to heat.',
        'People sensitive to heat should drink extra water and take breaks somewhere cool.',
    ),
    (
        'moderate', CalHeatScore.Score.MODERATE, '#ea8753',
        'Very warm day. A moderate increase in heat-related health impacts is expected among those sensitive to heat.',
        'People sensitive to heat should limit time outdoors in the afternoon, drink extra water, and stay somewhere cool during the hottest hours.',
    ),
    (
        'high', CalHeatScore.Score.HIGH, '#c23a00',
        'Hot day. An increase in heat-related health impacts is expected for everyone, especially those without access to adequate cooling and hydration or those engaged in strenuous physical activity outdoors. This level of heat can pose a significant risk to health.',
        'Everyone should drink extra water, limit strenuous outdoor activity, and spend the hottest hours somewhere cool.',
    ),
    (
        'severe', CalHeatScore.Score.SEVERE, '#700006',
        'Extreme heat day. A major increase in heat-related health impacts is expected for everyone, especially those without access to adequate cooling and hydration or those engaged in strenuous physical activity outdoors. This level of heat can pose a very serious risk to health.',
        'Everyone should stay somewhere cool when possible, drink at least 2 glasses of water an hour, and check on people at higher risk.',
    ),
]


def get_heat_scale():
    return Scale(
        id='heat-score',
        label='Heat Score',
        units='',
        kind='category',
        source=SOURCE,
        levels=tuple(
            ScaleLevel(
                key=key,
                label=score.label,
                color=color,
                tier=score.value,
                description=description,
                guidance=guidance,
                value=score.value,
            )
            for key, score, color, description, guidance in _LEVELS
        ),
    )
