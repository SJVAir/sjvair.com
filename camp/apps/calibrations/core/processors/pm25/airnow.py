from camp.apps.entries.models import PM25

from camp.apps.calibrations import processors
from ..airnow import AirNowNowCast

__all__ = ['PM25_AirNow_NowCast']


@processors.register()
class PM25_AirNow_NowCast(AirNowNowCast):
    """
    AirNow's PM2.5 NowCast, kept as CALIBRATED. It isn't the display
    value; AirNow PM2.5 still defaults to CLEANED.
    """
    name = 'PM25_AirNow_NowCast'
    entry_model = PM25
    next_stage = PM25.Stage.CALIBRATED
