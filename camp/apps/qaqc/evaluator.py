from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from camp.datasci.cleaning import has_sufficient_data


@dataclass
class HealthCheckResult:
    score: int = 0
    variance: Optional[float] = None
    correlation: Optional[float] = None

    @property
    def grade(self) -> str:
        return {2: 'A', 1: 'B', 0: 'F'}.get(self.score, 'F')


class HealthCheckEvaluator:
    def __init__(self, monitor, hour: datetime):
        """
        Args:
            dfs (dict): A mapping of sensor name to its hourly dataframe,
                        e.g. {'a': df_a, 'b': df_b} or {'1': df_1, '2': df_2}
        """
        from camp.apps.entries.models import PM25
        self.entry_model = PM25

        self.monitor = monitor
        self.hour = hour
        self.df = self.get_dataframe()

    def get_dataframe(self):
        queryset = self.entry_model.objects.filter(
            monitor_id=self.monitor.pk,
            timestamp__gte=self.hour,
            timestamp__lt=self.hour + timedelta(hours=1),
            stage=self.entry_model.Stage.RAW
        )
        return queryset.to_dataframe()

    def run_sanity_check(self, df: pd.DataFrame) -> bool:
        """
        Return True if this sensor passes all sanity checks.

        Why:
            Sane sensors must be within range, actively reporting, non-flat,
            non-noisy, and sufficiently complete.
        """
        return all([
            self.sensor_in_valid_range(df),
            self.sensor_is_not_flatlined(df),
            self.sensor_is_not_too_noisy(df),
            self.sensor_has_enough_data(df),
        ])

    def sensor_in_valid_range(self, df: pd.DataFrame) -> bool:
        """
        Check if all values fall within a plausible range.

        Why:
            Values outside 0–2000 µg/m³ are usually invalid or hardware noise.
        """
        return not df.empty and df['value'].between(0, 2000).all()

    def sensor_is_not_flatlined(self, df: pd.DataFrame) -> bool:
        """
        Detect flatlining - all values being the same or nearly the same.

        Why:
            Stuck or unresponsive sensors often emit a fixed value repeatedly.
        """
        return df['value'].nunique() > 1

    def sensor_is_not_too_noisy(self, df: pd.DataFrame, max_cv=1.0) -> bool:
        """
        Check if signal is excessively noisy (high coefficient of variation).

        Why:
            Very high variability may indicate interference or hardware instability.
        """
        if df.empty:
            return False
        mean = df['value'].mean()
        std = df['value'].std()
        if mean == 0:
            return False
        return (std / mean) <= max_cv

    def sensor_has_enough_data(self, df: pd.DataFrame) -> bool:
        """
        Ensure the sensor reported enough values during the time window.

        Why:
            Incomplete data may hide faults or cause misleading stats.
        """
        return has_sufficient_data(df,
            interval=self.monitor.EXPECTED_INTERVAL,
            window='1h',
            threshold=0.8
        )

    def get_variance(self) -> Optional[float]:
        """
        Calculate the relative difference between A and B means.

        Why:
            Low variance suggests close agreement; high variance suggests a mismatch.
        """
        mean_a = self.df_a['value'].mean()
        mean_b = self.df_b['value'].mean()
        if mean_a + mean_b == 0:
            return None
        return abs(mean_a - mean_b) / ((mean_a + mean_b) / 2)

    def get_correlation(self) -> Optional[float]:
        """
        Calculate the Pearson correlation between A and B values.

        Why:
            Correlation captures whether both sensors move together over time.
            Helps detect flatlining or misalignment even if averages match.
        """
        if len(self.df_a) < 2 or len(self.df_b) < 2:
            return None
        try:
            return self.df_a['value'].corr(self.df_b['value'])
        except Exception:
            return None

    def evaluate(self) -> HealthCheckResult:
        """
        Evaluate the current sensor dataset and return a structured result,
        including score, grade, variance, and correlation.

        Why we run sanity checks before checking variance:
            Even if variance is low, both sensors could be flatlined or misbehaving.
            Sanity checks ensure that low-variance readings are trustworthy.
        """
        if self.df is None:
            return HealthCheckResult(score=0)

        self.df_a, self.df_b = [
            self.df[self.df['sensor'] == sensor].copy()
            for sensor in self.monitor.ENTRY_CONFIG[self.entry_model]['sensors']
        ]

        a_ok = self.run_sanity_check(self.df_a)
        b_ok = self.run_sanity_check(self.df_b)

        variance = None
        correlation = None

        if a_ok and b_ok:
            variance = self.get_variance()
            correlation = self.get_correlation()
            score = 2 if (
                variance is not None and variance <= 0.10
                # and correlation is not None and correlation >= 0.6
            ) else 1

            return HealthCheckResult(score=score, variance=variance, correlation=correlation)

        score = 1 if a_ok or b_ok else 0
        return HealthCheckResult(score=score)
