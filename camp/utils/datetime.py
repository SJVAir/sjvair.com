from datetime import datetime, timedelta

from django import forms
from django.utils import timezone


def make_aware(timestamp):
    if timezone.is_naive(timestamp):
        return timezone.make_aware(timestamp)
    return timestamp


def parse_datetime(value, required=False):
    if isinstance(value, datetime):
        return make_aware(value)
    value = value.replace('T', ' ').strip('Z')
    value = forms.DateTimeField(required=required).clean(value)
    return make_aware(value)
