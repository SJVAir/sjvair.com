"""
The spray notice scale: one level, so the dashboard's map legend can name and colour the
notices layer from metadata. Served by `pesticides/meta/` under `scales`, keyed by the
catalog entry-type id, like the other domain scales.

The colour is a pink chosen to stand out over the use shading (blues), on light and dark
basemaps, and from the AQI, smoke and fire colours, with at least 3:1 contrast on white
and on dark backgrounds (count markers draw their number and outline in the background).
"""
from camp.utils.scales import Scale, ScaleLevel

from .places import SPRAYDAYS_URL

SOURCE = {
    'name': 'California Department of Pesticide Regulation, SprayDays',
    'url': SPRAYDAYS_URL,
}

NOTICE_COLOR = '#e64980'


def get_spray_notice_scale():
    return Scale(
        id='spray-notice',
        label='Spray Notices',
        units='',
        kind='category',
        source=SOURCE,
        levels=(
            ScaleLevel(key='notice', label='Spray notice', color=NOTICE_COLOR, tier=None, value='notice'),
        ),
    )
