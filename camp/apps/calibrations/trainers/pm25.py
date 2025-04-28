from camp.apps.calibrations.trainers.ml.linear import LinearRegressionTrainer
from camp.apps.entries import models as entry_models


class PM25_UnivariateLinearRegression(LinearRegressionTrainer):
    """
    Simple univariate linear regression for PM2.5 calibration.
    Uses PM2.5 as the single feature.
    """

    entry_model = entry_models.PM25
    target = 'value'
    features = ['value']
