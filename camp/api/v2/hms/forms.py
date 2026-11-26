from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

DEFAULT_DAYS = 30
MAX_DAYS = 366


class SmokePlaceForm(forms.Form):
    """The date range of a smoke/place/ request. Blank values are absent."""

    date__gte = forms.DateField(required=False)
    date__lte = forms.DateField(required=False)

    def __init__(self, data=None, *args, **kwargs):
        if data is not None:
            data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
        super().__init__(data, *args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        gte, lte = cleaned.get('date__gte'), cleaned.get('date__lte')
        today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
        if gte and lte:
            start, end = gte, lte
        elif gte:
            start, end = gte, today
        elif lte:
            start, end = lte - timedelta(days=DEFAULT_DAYS - 1), lte
        else:
            start, end = today - timedelta(days=DEFAULT_DAYS - 1), today

        if start > end:
            raise forms.ValidationError('date__gte must be on or before date__lte.')
        if (end - start).days + 1 > MAX_DAYS:
            raise forms.ValidationError(f'At most {MAX_DAYS} days per request.')
        cleaned['range'] = (start, end)
        return cleaned
