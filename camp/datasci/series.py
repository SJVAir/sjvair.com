from typing import NamedTuple, Optional

import pandas as pd

from . import stats


class SeriesSummary(NamedTuple):
    count: Optional[int]
    min: Optional[float]
    max: Optional[float]
    mean: Optional[float]

    stdev: Optional[float]
    variance: Optional[float]
    mad: Optional[float]

    range: Optional[float]
    flatline: Optional[float]

    @classmethod
    def from_series(cls, s: pd.Series) -> 'SeriesSummary':
        return cls(
            min=s.min(),
            max=s.max(),
            count=s.count(),
            mean=s.mean(),
            stdev=s.std(),
            variance=s.var(ddof=1),
            mad=stats.mad(s),
            range=stats.signal_range(s),
            flatline=stats.flatline_ratio(s),
        )

    def as_dict(self, suffix=''):
        data = self._asdict()
        if suffix:
            return {f'{key}_{suffix}': value for key, value in data.items()}
        return data


class SeriesComparison(NamedTuple):
    a: SeriesSummary
    b: SeriesSummary
    rpd_means: Optional[float]
    rpd_pairwise: Optional[float]
    rmse: Optional[float]
    correlation: Optional[float]

    @classmethod
    def from_series(cls, a: pd.Series, b: pd.Series) -> 'SeriesComparison':
        return cls(
            a=SeriesSummary.from_series(a),
            b=SeriesSummary.from_series(b),
            rpd_means=stats.rpd_means(a, b),
            rpd_pairwise=stats.rpd_pairwise(a, b),
            rmse=stats.rmse(a, b),
            correlation=stats.correlation(a, b),
        )

    def as_dict(self, flat: bool = False) -> dict:
        data = self._asdict()
        if flat:
            data.update(data.pop('a').as_dict('a'))
            data.update(data.pop('b').as_dict('b'))
        else:
            data['a'] = data.pop('a').as_dict()
            data['b'] = data.pop('b').as_dict()
        return data


def summarize(series: pd.Series) -> SeriesSummary:
    return SeriesSummary.from_series(series)


def compare(a: pd.Series, b: pd.Series) -> SeriesComparison:
    """
    Compare two aligned sensor value series.
    Returns a dict with summary statistics for QA/QC.
    """
    return SeriesComparison.from_series(a, b)
