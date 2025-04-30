import pandas as pd


def filter_by_completeness(df, interval='2min', resample='1h', threshold=0.8):
    """
    Resample a time-indexed DataFrame and retain only those intervals
    that meet the minimum completeness threshold.

    Args:
        df (pd.DataFrame): Time-indexed DataFrame.
        resample (str): Interval to group by (e.g., '1h', '1d').
        interval (str): Interval between expected entries (e.g., '2min').
        threshold (float): Required completeness between 0 and 1.

    Returns:
        pd.DataFrame: Filtered DataFrame.
    """
    if df.empty:
        return df

    expected_count = int(pd.Timedelta(resample) / pd.Timedelta(interval))
    counts = df.resample(resample).count()
    valid_mask = (counts >= expected_count * threshold).all(axis=1)
    return df.resample(resample).mean().loc[valid_mask]
