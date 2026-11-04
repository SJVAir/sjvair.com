from camp.utils.scales import Scale, ScaleLevel

from camp.apps.entries import levels

SOURCE = {
    'name': 'San Joaquin Valley APCD, Check Before You Burn',
    'url': 'https://ww2.valleyair.org/',
}

# (key, value, label, color). `value` is the feed's burnStatus `status`
# attribute exactly as stored in Forecast.burn_status.
#
# The district's third status, "No Burning For All" (#ff0000), is left out: its
# `status` string has never been seen in the feed and couldn't be confirmed.
# Add it here once it is observed; until then the ingest task logs any value
# not listed.
_BURN_LEVELS = [
    ('discouraged', 'Discouraged', 'Burning Discouraged', '#ffff00'),
    ('registered', 'Registered', 'No Burning Unless Registered', '#ff7e00'),
]

BURN_STATUS_VALUES = {value for _, value, _, _ in _BURN_LEVELS}


def get_aqi_forecast_scale():
    return levels.AQI.to_scale('aqi-forecast', 'AQI Forecast', 'AQI')


def get_burn_status_scale():
    return Scale(
        id='burn-status',
        label='Burn Status',
        units='',
        kind='category',
        source=SOURCE,
        levels=tuple(
            ScaleLevel(key=key, label=label, color=color, tier=None, value=value)
            for key, value, label, color in _BURN_LEVELS
        ),
    )
