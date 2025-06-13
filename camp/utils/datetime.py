from datetime import datetime

from django import forms
from django.conf import settings
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
