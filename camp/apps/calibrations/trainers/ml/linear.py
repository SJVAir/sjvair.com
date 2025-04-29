from datetime import timedelta

from camp.apps.calibrations.trainers.base import BaseTrainer
from camp.datasci.linear import LinearRegression


class LinearRegressionTrainer(BaseTrainer):
    days = [7, 14, 21, 28]

    resample_freq = 'h'
    min_r2 = 0.6

    def get_common_lookup(self, days):
        start_time = self.end_date - timedelta(days=days)
        return {
            'timestamp__range': (start_time, self.end_date),
        }

    def get_feature_dataframe(self, **kwargs):
        defaults = {'stage': self.pair.colocated_stage}
        defaults.update(kwargs)

        queryset = self.get_feature_queryset(**defaults)
        df = queryset.to_dataframe(fields=['timestamp'] + self.features)

        if df is not None:
            df = df.resample(self.resample_freq).mean()
            return df[self.features]

    def get_target_series(self, **kwargs):
        defaults = {'stage': self.pair.reference_stage}
        defaults.update(kwargs)

        queryset = self.get_target_queryset(**defaults)
        df = queryset.to_dataframe(fields=['timestamp', self.target])

        if df is not None:
            df = df.resample(self.resample_freq).mean()
            return df[self.target]

    def process(self):
        best_regression = None

        for days in self.days:
            lookup = self.get_common_lookup(days)

            feature_df = self.get_feature_dataframe(**lookup)
            target_series = self.get_target_series(**lookup)

            if feature_df is None or target_series is None:
                continue

            model = LinearRegression(
                features=feature_df,
                target=target_series
            )

            results = model.fit()

            if best_regression is None or results.r2 > best_regression.r2:
                best_regression = results

        if best_regression:
            return self.build_calibration(best_regression)

    def is_valid(self, result):
        return result.r2 >= self.min_r2

    def build_calibration(self, result):
        defaults = {
            'r2': result.r2,
            'rmse': result.rmse,
            'mae': result.mae,
            'intercept': result.intercept,
            'formula': result.formula,
            'features': list(result.coefs.keys()),
            'metadata': {
                'coefs': result.coefs,
            },
        }
        return super().build_calibration(**defaults)
