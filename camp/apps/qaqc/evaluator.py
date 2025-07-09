from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from camp.datasci import series
from camp.apps.monitors.models import Monitor


@dataclass
class SanityChecks:
    summary: series.SeriesSummary
    monitor: Monitor
    results: dict[str, Optional[bool]] = field(init=False)

    def __post_init__(self):
        self.results = {
            'max': self.check_max(),
            'flatline': self.check_flatline(),
            'completeness': self.check_completeness(),
        }

    @property
    def ok(self) -> bool:
        return all(self.results.values())

    def as_dict(self, suffix, flat: bool = True) -> dict:
        if not flat:
            return {f'sanity_{suffix}': self.results}
        return {
            f'sanity_{k}_{suffix}': v for k, v in self.results.items()
        }

    def check_max(self) -> bool:
        """
        Check if all values fall within a plausible range.

        Why:
            Values outside 0–2000 µg/m³ are usually invalid or hardware noise.
        """
        if self.summary.max is None or pd.isna(self.summary.max):
            return None
        return self.summary.max < 1500

    def check_flatline(self) -> bool:
        """
        Detect flatlining - all values being the same or nearly the same.

        Why:
            Stuck or unresponsive sensors often emit a fixed value repeatedly.
        """
        if self.summary.flatline is None or pd.isna(self.summary.flatline):
            return None
        return self.summary.flatline < .75

    def check_completeness(self) -> bool:
        """
        Ensure the sensor reported enough values during the time window.

        Why:
            Incomplete data may hide faults or cause misleading stats.
        """
        if self.summary.count is None or pd.isna(self.summary.count):
            return None
        expected = self.monitor.expected_hourly_entries
        return (self.summary.count / expected) >= .8


@dataclass
class HealthCheckResult:
    score: int = 0
    summary: Optional[series.SeriesComparison] = None
    sanity_a: Optional[SanityChecks] = None
    sanity_b: Optional[SanityChecks] = None

    @property
    def grade(self) -> str:
        return {2: 'A', 1: 'B', 0: 'F'}.get(self.score, 'F')

    def as_dict(self, flat: bool = True) -> dict:
        data = {'score': self.score, 'grade': self.grade}
        if self.summary:
            data.update(self.summary.to_dict(flat=flat))
        if self.sanity_a:
            data.update(self.sanity_a.to_dict('a', flat=flat))
        if self.sanity_b:
            data.update(self.sanity_b.to_dict('b', flat=flat))
        return data


class HealthCheckEvaluator:
    def __init__(self, monitor, hour: datetime):
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

    def get_score(self) -> int:
        if self.sanity_a.ok and self.sanity_b.ok:
            return 2 if self.summary.rpd_pairwise <= 20 else 1
        return 1 if self.sanity_a.ok or self.sanity_b.ok else 0

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

        self.summary = series.compare(self.df_a['value'], self.df_b['value'])
        self.sanity_a = SanityChecks(summary=self.summary.a, monitor=self.monitor)
        self.sanity_b = SanityChecks(summary=self.summary.b, monitor=self.monitor)
        score = self.get_score()

        return HealthCheckResult(
            score=score,
            summary=self.summary,
            sanity_a=self.sanity_a,
            sanity_b=self.sanity_b,
        )
