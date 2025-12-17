from datetime import timedelta

from camp.apps.calibrations.core.trainers.base import BaseTrainer
from camp.apps.entries.timelines import ResolvedEntryTimeline
from camp.datasci.cleaning import filter_by_completeness
from camp.datasci.linear import LinearRegression


class LinearRegressionTrainer(BaseTrainer):
    days = [7, 14, 21, 28]

    resample_freq = '1h'
    min_completeness = 0.8
    min_r2 = 0.6

    def get_entry_types(self):
        """
        Returns the list of entry models needed to fetch features.
        By default, uses only the declared entry_model.
        """
        return [self.entry_model]

    def get_sample(self, monitor, sample, days):
        start_time = self.end_time - timedelta(days=days)
        builder = ResolvedEntryTimeline(
            monitor=monitor,
            entry_types=self.get_entry_types(),
            start_time=start_time,
            end_time=self.end_time,
        )
        df = builder.to_dataframe()

        if not df.empty:
            if self.min_completeness:
                df = filter_by_completeness(df,
                    interval=monitor.EXPECTED_INTERVAL,
                    resample=self.resample_freq,
                    threshold=self.min_completeness,
                )

            df = df.resample(self.resample_freq).mean()
            field_map = builder.get_field_map(self.entry_model)

            if isinstance(sample, str):
                remapped = field_map.get(sample, sample)
                return df[remapped]
            elif isinstance(sample, list):
                remapped = [field_map.get(field, field) for field in sample]
                return df[remapped]

    def get_feature_dataframe(self, days):
        return self.get_sample(self.pair.colocated, self.features, days)

    def get_target_series(self, days):
        return self.get_sample(self.pair.reference, self.target, days)

    def has_required_data(self, feature_df, target_series):
        '''
        Checks whether the features and target contain any usable data.
        '''
        if feature_df is None or target_series is None:
            return False

        if feature_df.empty or target_series.empty:
            return False

        # Ensure all feature columns exist
        for col in self.features:
            if col not in feature_df.columns:
                return False

            if feature_df[col].dropna().empty:
                return False

        if target_series.dropna().empty:
            return False

        return True

    def process(self):
        best_regression = None

        for days in self.days:
            feature_df = self.get_feature_dataframe(days=days)
            target_series = self.get_target_series(days=days)

            if not self.has_required_data(feature_df, target_series):
                continue

            model = LinearRegression(
                features=feature_df,
                target=target_series
            )

            regression = model.fit()

            if best_regression is None or regression.r2 > best_regression.r2:
                regression.start_time = self.end_time - timedelta(days=days)
                regression.end_time = self.end_time
                best_regression = regression

        if best_regression:
            return self.build_calibration(best_regression)

    def is_valid(self, regression):
        current = self.pair.get_current_calibration(self.name)

        if current and current.end_time:
            timesince = self.end_time - current.end_time
            if timesince < timedelta(days=7):
                return regression.r2 > current.r2
            elif timesince < timedelta(days=30):
                return regression.r2 > 0.75

        return regression.r2 > self.min_r2

    def build_calibration(self, regression):
        defaults = {
            'formula': regression.formula,
            'intercept': regression.intercept,
            'start_time': getattr(regression, 'start_time', None),
            'end_time': getattr(regression, 'end_time', None),
            'r2': regression.r2,
            'rmse': regression.rmse,
            'mae': regression.mae,
            'features': list(regression.coefs.keys()),
            'metadata': {
                'coefs': regression.coefs,
            },
        }
        return super().build_calibration(**defaults)
