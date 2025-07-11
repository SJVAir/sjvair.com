from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class BaseResults:
    '''
    Base class for all model results.
    '''
    r2: float
    variance: float
    rmse: float
    mae: float


@dataclass
class RegressionResults(BaseResults):
    '''
    Specialized results for regression models.
    '''
    coefs: Dict[str, float]
    intercept: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def formula(self):
        """
        Build a basic linear regression formula string: e.g., (2.5 * feature1) + (1.2 * feature2) + 3
        """
        terms = [f'({feature} * {coef:.6f})' for feature, coef in self.coefs.items()]
        formula = ' + '.join(terms)
        formula += f' + {self.intercept:.6f}'
        return formula


@dataclass
class ModelResults(BaseResults):
    '''
    Generic results for machine learning models (e.g., XGBoost, RandomForest).
    No intercept or formula, but has optional metadata.
    '''
    blob_path: Optional[str] = None  # path to saved model file
    model_name: Optional[str] = None  # e.g., 'XGBoost', 'LSTM'
    metadata: Dict[str, Any] = field(default_factory=dict)
