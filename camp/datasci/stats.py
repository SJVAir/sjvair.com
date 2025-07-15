from typing import Optional

import numpy as np
import pandas as pd


def correlation(a: pd.Series, b: pd.Series, method: str = 'spearman') -> Optional[float]:
    """
    Return the correlation between two Series using the specified method,
    or None if not computable.
    """
    if method not in {'pearson', 'spearman', 'kendall'}:
        raise ValueError(f'Unsupported correlation method: {method}')

    if len(a) < 2 or len(b) < 2:
        return None

    if not a.std() or not b.std():
        return None

    try:
        return a.corr(b, method=method)
    except Exception:
        return None


def flatline_ratio(series: pd.Series) -> float:
    """Return the percent of repeated (flatlined) values in the series."""
    return (series.diff().dropna() == 0).mean()


def mad(series: pd.Series) -> float:
    """Return the Median Absolute Deviation (MAD) of the series."""
    median = series.median()
    return (series - median).abs().median()


def rmse(a_values: pd.Series, b_values: pd.Series) -> float:
    """Root Mean Squared Error between two sequences."""
    return float(np.sqrt(((a_values - b_values) ** 2).mean()))


def rpd(a: float, b: float) -> float:
    """Return the Relative Percent Difference (RPD) between two values."""
    mean = (a + b) / 2
    return (abs(a - b) / mean) if mean else 0.0


def rpd_means(a: pd.Series, b: pd.Series) -> float:
    """Return the RDP of the means of two Series."""
    return rpd(a.mean(), b.mean())


def rpd_pairwise(a: pd.Series, b: pd.Series) -> float:
    """Return the mean RPD across all paired values in two Series."""
    return ((a - b).abs() / ((a + b) / 2)).mean()


def signal_range(series: pd.Series) -> float:
    """Return the range (max - min) of the series."""
    return series.max() - series.min()


def variance(series: pd.Series) -> float:
    """Sample variance (ddof=1) of a series."""
    return float(series.var(ddof=1))
