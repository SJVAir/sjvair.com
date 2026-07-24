from decimal import Decimal

from camp.apps.entries.models import O3
from camp.apps.calibrations import processors
from .ml.linear import LinearExpressionProcessor


@processors.register()
class O3_VOZBox(LinearExpressionProcessor):
    entry_model = O3
    required_stage = O3.Stage.RAW
    next_stage = O3.Stage.CALIBRATED
    required_context = ['temperature', 'humidity']
    min_required_value = Decimal('0.0')
