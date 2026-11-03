from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.ml.linear import LinearExpressionProcessor
from camp.apps.entries import models as entry_models

__all__ = ['PM25_UnivariateLinearRegression', 'PM25_MultivariateLinearRegression']


@processors.register()
class PM25_UnivariateLinearRegression(LinearExpressionProcessor):
    label = "Linear calibration (PM2.5 only)"
    description = (
        "Adjusts low-cost sensor PM2.5 with a straight-line fit built by comparing nearby sensors to a reference monitor."
    )
    entry_model = entry_models.PM25
    required_context = ['pm25']
    required_stage = entry_models.PM25.Stage.CLEANED
    next_stage = entry_models.PM25.Stage.CALIBRATED


@processors.register()
class PM25_MultivariateLinearRegression(LinearExpressionProcessor):
    label = "Linear calibration (with weather)"
    description = (
        "Adjusts low-cost sensor PM2.5 using a fit to a reference monitor that also accounts for temperature and humidity."
    )
    entry_model = entry_models.PM25
    required_context = ['pm25', 'temperature', 'humidity']
    required_stage = entry_models.PM25.Stage.CLEANED
    next_stage = entry_models.PM25.Stage.CALIBRATED
