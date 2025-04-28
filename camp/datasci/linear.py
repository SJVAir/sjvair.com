from dataclasses import dataclass
from sklearn.linear_model import LinearRegression as SklearnLinearRegression


@dataclass
class LinearRegressionResults:
    r2: float
    intercept: float
    # variance: float
    coefs: dict


class LinearRegression:
    def __init__(self, features, target):
        """
        Args:
            features (pd.DataFrame): The feature columns (X)
            target (pd.Series or pd.DataFrame): The target column (y)
        """
        self.features = features
        self.target = target
        self.model = None

    def fit(self):
        """
        Fits a linear regression model and returns the results.
        """
        self.model = SklearnLinearRegression()
        self.model.fit(self.features, self.target)

        coefficients = {
            feature: coef
            for feature, coef in zip(self.features.columns, self.model.coef_)
        }

        return LinearRegressionResults(
            r2=self.model.score(self.features, self.target),
            intercept=self.model.intercept_,
            coefs=coefficients
        )
