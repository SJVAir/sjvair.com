from datetime import timedelta

from camp.apps.calibrations.models import Calibration
from camp.datasci.models import LinearRegression


class LinearRegressionTrainer(BaseTrainer):
    days = [7, 14, 21, 28]

    resample_freq = 'h'
    min_r2 = 0.6

    def get_common_lookup(self, days):
        start_time = self.end_date - timedelta(days=days)
        return {
            'timestamp__range': (start_time, self.end_date),
        }

    def feature_suffix(self, value=''):
        return f'{value}_feature'

    def target_suffix(self, value=''):
        return f'{value}_target'

    def get_feature_dataframe(self, **kwargs):
        defaults = {'stage': self.pair.colocated_stage}
        defaults.update(kwargs)

        queryset = self.get_feature_queryset(**defaults)

        df = queryset.to_dataframe(fields=['timestamp'] + self.features)
        df = df.resample(self.resample_freq).mean()
        return df

    def get_target_dataframe(self, **kwargs):
        defaults = {'stage': self.pair.reference_stage}
        defaults.update(kwargs)

        queryset = self.get_target_queryset(**defaults)

        df = queryset.to_dataframe(fields=['timestamp', self.target])
        df = df.resample(self.resample_freq).mean()
        return df

    def process(self):
        best_regression = None

        for days in self.days:
            lookup = self.get_common_lookup(days)

            feature_df = self.get_feature_dataframe(**lookup)
            target_df = self.get_target_dataframe(**lookup)

            if feature_df.empty or target_df.empty:
                continue

            df = feature_df.join(
                target_df,
                how='inner',
                lsuffix=self.feature_suffix(),
                rsuffix=self.target_suffix()
            ).dropna()

            if df.empty:
                continue

            features = [
                self.feature_suffix(f) if f == self.target else f
                for f in self.features
            ]
            target = (
                self.target_suffix(self.target)
                if self.target in self.features
                else self.target
            )

            model = UnivariateLinearRegression(
                features=df[features],
                target=df[target]
            )

            results = model.fit()

            if best_regression is None or results.r2 > best_regression.r2:
                best_regression = results

        return best_regression

    def is_valid(self, result):
        return result.r2 >= self.min_r2

    def to_calibration(self, result):
        """
        Takes a regression result and packages it into a Calibration model (unsaved).
        """
        return Calibration(
            pair_id=self.pair.pk,
            entry_type=self.pair.entry_type,
            trainer=self.name,
            formula=result.formula,
            intercept=result.intercept,
            r2=result.r2,
            rmse=None,  # We can calculate this later if we want
            mae=None,
            features=list(result.coefs.keys()),
            metadata={
                'coefs': result.coefs,
            },
        )
