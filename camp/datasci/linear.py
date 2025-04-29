import pandas as pd

from django.utils.functional import cached_property

from sklearn.linear_model import LinearRegression as SklearnLinearRegression
from sklearn.metrics import r2_score, explained_variance_score, mean_absolute_error, root_mean_squared_error

from camp.datasci.results import RegressionResults


class LinearRegression:
    def __init__(self, features: pd.DataFrame, target: pd.Series):
        """
        Args:
            features (pd.DataFrame): The feature columns (X)
            target (pd.Series): The target column (y)
        """
        self.input_features = features
        self.input_target = target
        self.model = None

    def feature_suffix(self, value=''):
        return f'{value}_feature'

    def target_suffix(self, value=''):
        return f'{value}input_target'

    def feature_unsuffix(self, name):
        suffix = self.feature_suffix()
        if name.endswith(suffix):
            return name[: -len(suffix)]
        return name

    @cached_property
    def merged_df(self):
        return self.input_features.join(
            self.input_target,
            how='inner',
            lsuffix=self.feature_suffix(),
            rsuffix=self.target_suffix()
        ).dropna()

    @cached_property
    def features(self):
        features = [
            self.feature_suffix(f) if f == self.input_target.name else f
            for f in self.input_features.columns
        ]
        return self.merged_df[features]

    @cached_property
    def target(self):
        target = (
            self.target_suffix(self.input_target.name)
            if self.input_target.name in self.input_features.columns
            else self.input_target.name
        )
        return self.merged_df[target]

    def fit(self):
        if self.features.empty or self.target.empty:
            return

        self.model = SklearnLinearRegression()
        self.model.fit(self.features, self.target)

        predictions = self.model.predict(self.features)
        coefficients = {
            self.feature_unsuffix(feature): coef
            for feature, coef in zip(self.features.columns, self.model.coef_)
        }

        return RegressionResults(
            r2=r2_score(self.target, predictions),
            variance=explained_variance_score(self.target, predictions),
            rmse=root_mean_squared_error(self.target, predictions),
            mae=mean_absolute_error(self.target, predictions),
            coefs=coefficients,
            intercept=self.model.intercept_,
        )
