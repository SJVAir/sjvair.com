from decimal import Decimal

from camp.apps.entries.models import O3
from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.ml.linear import LinearExpressionProcessor


@processors.register()
class O3_VOZBox(LinearExpressionProcessor):
    entry_model = O3
    required_stage = O3.Stage.RAW
    next_stage = O3.Stage.CALIBRATED
    required_context = ['temperature', 'humidity']
    min_required_value = Decimal('0.0')


@processors.register()
class VOZBox_QuinnCal:
    """
    Not a per-entry processor -- QuinnResearch (CCEJN's upstream data
    provider) already computes calibrated O3 themselves and publishes it
    as o3_cal alongside the raw values in moospmV3_cal. We just record
    it under this name so DefaultCalibration can reference it and
    update_latest_entry recognizes it as the display value, instead of
    writing these entries with a blank/anonymous processor.
    """
    name = 'VOZBox_QuinnCal'
    entry_model = O3
    next_stage = O3.Stage.CALIBRATED
