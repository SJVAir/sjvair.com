from camp.apps.entries.models import PM100

from camp.apps.calibrations import processors
from ..airnow import AirNowNowCast

__all__ = ['PM100_AirNow_NowCast']


@processors.register()
class PM100_AirNow_NowCast(AirNowNowCast):
    """
    AirNow's PM10 NowCast, kept as CALIBRATED. It isn't the display
    value; AirNow PM10 still defaults to RAW.
    """
    name = 'PM100_AirNow_NowCast'
    entry_model = PM100
    next_stage = PM100.Stage.CALIBRATED
