from datetime import datetime
from functools import lru_cache

import pandas as pd

from django.conf import settings
from django.utils.text import slugify


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


def generate_export_path(monitor, start_date, end_date, ext='csv'):
    """
    Generates a timestamped export path for storing monitor data exports.

    Example:
        exports/2025/07/1234_2025-01-01_2025-06-30_abcd1234.csv
    """
    now = datetime.utcnow()
    timestamp_path = now.strftime('%Y/%m')
    bits = [slugify(monitor.name)]
    if hasattr(monitor, 'purple_id'):
        bits.append(monitor.purple_id)
    if hasattr(monitor, 'location_id'):
        bits.append(monitor.location_id)
    bits.extend([monitor.pk.hex_grouped, start_date, end_date])
    filename = '_'.join([str(b) for b in bits])
    filename = f'{filename}.{ext}'
    return f'exports/{timestamp_path}/{filename}'


def to_multi_entry_wide_dataframe(monitor, start_date, end_date, entry_types=None):
    """
    Returns a wide-format DataFrame of entry values for a given monitor across multiple entry models.
    Each row is a unique (timestamp, sensor) pair.
    Columns are named like 'pm25_cleaned', 'humidity_raw', 'o3_modelx', etc.
    """

    entry_types = entry_types or monitor.entry_types
    dfs = []

    for model in entry_types:
        lookup = {
            'monitor_id': monitor.pk,
            'timestamp__gte': start_date,
            'timestamp__lt': end_date,
        }

        qs = model.objects.filter(**lookup)
        df = qs.to_dataframe()

        if df is None or df.empty:
            continue

        df = df.reset_index()

        def label_row(row):
            bits = [model.entry_type]
            if row['sensor']:
                bits.append(row['sensor'])
            bits.append(row['processor'] if row['stage'] == model.Stage.CALIBRATED else row['stage'])
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
