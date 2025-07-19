from functools import lru_cache

import pandas as pd

from django.conf import settings


@lru_cache
def get_all_entry_models(base_class=None):
    from camp.apps.entries.models import BaseEntry
    base_class = base_class or BaseEntry
    subclasses = set()

    def recurse(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, '_meta') and not subclass._meta.abstract:
                subclasses.add(subclass)
            recurse(subclass)

    recurse(base_class)
    return subclasses


@lru_cache()
def get_entry_model_by_name(name):
    name = name.lower()
    for model in get_all_entry_models():
        if model._meta.model_name == name:
            return model


def to_multi_entry_wide_dataframe(entry_models, monitor, start=None, end=None):
    """
    Returns a wide-format DataFrame of entry values for a given monitor across multiple entry models.
    Each row is a unique (timestamp, sensor) pair.
    Columns are named like 'pm25_cleaned', 'humidity_raw', 'o3_modelx', etc.
    """

    dfs = []

    for model in entry_models:
        lookup = {'monitor_id': monitor.pk}
        if start:
            lookup['timestamp__gte'] = start
        if end:
            lookup['timestamp__lt'] = end

        qs = model.objects.filter(**lookup)
        df = qs.to_dataframe()

        if df is None or df.empty:
            continue

        df = df.reset_index()

        def label_row(row):
            bits = [model.entry_type, row['processor'] if row['stage'] == model.Stage.CALIBRATED else row['stage']]
            if row['sensor']:
                bits.append(row['sensor'])
            return '_'.join(bits)

        df['column_key'] = df.apply(label_row, axis=1)
        dfs.append(df[['timestamp', 'sensor', 'column_key', *model.declared_field_names]])

    if not dfs:
        return pd.DataFrame()

    pivoted = (pd
        .concat(dfs, axis=0)
        .pivot_table(
            index='timestamp',
            columns='column_key',
            values='value'
        )
        .reset_index()
    )
    pivoted.columns.name = None

    # Add a local timestamp column right after the UTC timestamp
    pivoted['timestamp_local'] = pivoted['timestamp'].dt.tz_convert(settings.DEFAULT_TIMEZONE)
    ts_index = pivoted.columns.get_loc('timestamp')
    pivoted.insert(ts_index + 1, 'timestamp_local', pivoted.pop('timestamp_local'))

    return pivoted
