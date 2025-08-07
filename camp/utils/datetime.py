from datetime import datetime, time, timedelta

from django import forms
from django.utils import timezone


def make_aware(timestamp, tz=timezone.utc):
    if timezone.is_naive(timestamp):
        return timezone.make_aware(timestamp, tz)
    return timestamp


def parse_datetime(value, required=False):
    if not isinstance(value, datetime):
        value = forms.DateTimeField(required=required).clean(value)
    return make_aware(value)


def parse_timestamp(value):
    if isinstance(value, int):
        value = datetime.fromtimestamp(value)
    elif isinstance(value, str):
        value = forms.DateTimeField().clean(value)
    return make_aware(value)


def chunk_date_range(start_date, end_date, days=28):
    '''Splits a date range into chunks, each `days` long.'''

    chunks = []
    current_date = start_date

    while current_date <= end_date:
        period_end_date = current_date + timedelta(days=days - 1)
        chunk_end_date = min(period_end_date, end_date)
        chunks.append((
            datetime.combine(current_date, time.min),
            datetime.combine(chunk_end_date, time.max),
        ))
        current_date = chunk_end_date + timedelta(days=1)

    return chunks
