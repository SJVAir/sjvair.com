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
