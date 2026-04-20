from datetime import datetime, time, timedelta

from django import forms
from django.conf import settings
from django.utils import timezone


def localtime(value=None):
    """Convert a datetime to the project's local timezone (America/Los_Angeles).

    Equivalent to Django's timezone.localtime() if TIME_ZONE were set to LA
    rather than UTC.
    """
    return timezone.localtime(value, timezone=settings.DEFAULT_TIMEZONE)


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
    '''Splits a date(time) range into chunks, each `days` long.'''

    chunks = []
    current_date = start_date

    while current_date <= end_date:
        period_end_date = current_date + timedelta(days=days - 1)
        chunk_end_date = min(period_end_date, end_date)
        chunks.append((
            current_date if isinstance(current_date, datetime) else datetime.combine(current_date, time.min),
            chunk_end_date if isinstance(chunk_end_date, datetime) else datetime.combine(chunk_end_date, time.max),
        ))
        current_date = chunk_end_date + timedelta(days=1)

    return chunks
