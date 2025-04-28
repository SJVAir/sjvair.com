from django.test import TestCase

import pandas as pd

from camp.datasci.linear import LinearRegression
from camp.utils.test import is_close


class PurpleAirTests(TestCase):
    def test_univariate_regression(self):
        # Simple linear data: y = 2x + 1
        df = pd.DataFrame({
            'feature1': [1, 2, 3, 4, 5],
            'target': [3, 5, 7, 9, 11]
        })

        model = LinearRegression(
            features=df[['feature1']],
            target=df['target']
        )

        results = model.fit()

        assert abs(results.r2 - 1.0) < 1e-6
        assert abs(results.intercept - 1.0) < 1e-6
        assert abs(results.coefs['feature1'] - 2.0) < 1e-6


    def test_multivariate_regression(self):
        # Multivariate: y = 3*a + 2*b + 1
        df = pd.DataFrame({
            'a': [1, 2, 1, 4, 3],
            'b': [5, 1, 2, 3, 5],
            'target': [
                3*1 + 2*5 + 1,  # 3 + 10 + 1 = 14
                3*2 + 2*1 + 1,  # 6 + 2 + 1 = 9
                3*1 + 2*2 + 1,  # 3 + 4 + 1 = 8
                3*4 + 2*3 + 1,  # 12 + 6 + 1 = 19
                3*3 + 2*5 + 1,  # 9 + 10 + 1 = 20
            ]
        })

        model = LinearRegression(
            features=df[['a', 'b']],
            target=df['target']
        )

        results = model.fit()

        assert is_close(results.r2, 1.0, 1e-6)
        assert is_close(results.intercept, 1.0, 1e-6)
        assert is_close(results.coefs['a'], 3.0, 1e-6)
        assert is_close(results.coefs['b'], 2.0, 1e-6)
