from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from camp.utils.datetime import make_aware
from camp.utils.forms import LatLonForm


class TempoSeriesForm(forms.Form):
    start = forms.DateTimeField(required=False)
    end = forms.DateTimeField(required=False)

    MAX_RANGE = timedelta(days=90)  # matches sync_tempo_reprocessing's existing rolling-window convention

    def clean(self):
        cleaned_data = super().clean()
        start, end = cleaned_data.get('start'), cleaned_data.get('end')

        if start is not None and timezone.is_naive(start):
            start = make_aware(start, tz=settings.DEFAULT_TIMEZONE)
        if end is not None and timezone.is_naive(end):
            end = make_aware(end, tz=settings.DEFAULT_TIMEZONE)

        if start is None and end is not None:
            start = end
        elif end is None and start is not None:
            end = start

        if start is not None and end is not None:
            if start > end:
                raise forms.ValidationError('start must be before end.')
            if end - start > self.MAX_RANGE:
                raise forms.ValidationError(f'Maximum range is {self.MAX_RANGE.days} days.')

        cleaned_data['start'], cleaned_data['end'] = start, end
        return cleaned_data


class TempoPointForm(LatLonForm, TempoSeriesForm):
    pass
