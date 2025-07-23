from camp.apps.calibrations import trainers
from camp.apps.calibrations.core.trainers.ml.linear import LinearRegressionTrainer
from camp.apps.entries import models as entry_models


@trainers.register()
class PM25_UnivariateLinearRegression(LinearRegressionTrainer):
    """
    Simple univariate linear regression for PM2.5 calibration.
    Uses PM2.5 as the single feature.
    """

    entry_model = entry_models.PM25
    target = 'pm25'
    features = ['pm25']


@trainers.register()
class PM25_MultivariateLinearRegression(LinearRegressionTrainer):
    """
    Multivariate linear regression for PM2.5 calibration.
    Uses PM2.5, Temperature, and Humidity as the features.
    """

    entry_model = entry_models.PM25
    target = 'pm25'
    features = ['pm25', 'temperature', 'humidity']

    def get_entry_types(self):
        from camp.apps.entries import models as entry_models
        return [
            entry_models.PM25,
            entry_models.Temperature,
            entry_models.Humidity
        ]
