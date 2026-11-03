from camp.apps.entries.models import O3

from camp.apps.calibrations import processors
from ..airnow import AirNowNowCast

__all__ = ['O3_AirNow_NowCast']


@processors.register()
class O3_AirNow_NowCast(AirNowNowCast):
    """
    AirNow's ozone NowCast, kept as CALIBRATED. It isn't the display
    value; AirNow O3 still defaults to RAW.
    """
    label = "AirNow NowCast"
    description = (
        "AirNow's own NowCast, a weighted average of recent hours of ozone that emphasizes the latest hours when air quality is changing quickly."
    )
    name = 'O3_AirNow_NowCast'
    entry_model = O3
    next_stage = O3.Stage.CALIBRATED
