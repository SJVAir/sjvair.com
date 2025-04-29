from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.ml.linear import LinearExpressionProcessor
from camp.apps.entries import models as entry_models

__all__ = ['PM25_UnivariateLinearRegression', 'PM25_MultivariateLinearRegression']


@processors.register()
class PM25_UnivariateLinearRegression(LinearExpressionProcessor):
    entry_model = entry_models.PM25
    required_context = ['pm25']
    required_stage = entry_models.PM25.Stage.CLEANED
    next_stage = entry_models.PM25.Stage.CALIBRATED


@processors.register()
class PM25_MultivariateLinearRegression(LinearExpressionProcessor):
    entry_model = entry_models.PM25
    required_context = ['pm25', 'temperature', 'humidity']
    required_stage = entry_models.PM25.Stage.CLEANED
    next_stage = entry_models.PM25.Stage.CALIBRATED
