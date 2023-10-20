from datetime import datetime, timedelta

from django import forms
from django.utils import timezone


def make_aware(timestamp, tz=None):
    if timezone.is_naive(timestamp):
        return timezone.make_aware(timestamp, tz)
    return timestamp


def parse_datetime(value, required=False):
    if not isinstance(value, datetime):
        value = value.replace('T', ' ').strip('Z')
        value = forms.DateTimeField(required=required).clean(value)
    return make_aware(value)


def parse_timestamp(value):
    if isinstance(value, int):
        value = datetime.fromtimestamp(value)
    elif isinstance(value, str):
        value = value.replace('T', ' ').strip('Z')
        value = forms.DateTimeField().clean(value)
    return make_aware(value)
