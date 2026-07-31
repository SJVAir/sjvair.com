from datetime import timedelta

from django import forms
from django.conf import settings
from django.db.models import enums
from django.utils import timezone

from camp.utils.datetime import make_aware


class EntryExportForm(forms.Form):
    class Scope(enums.TextChoices):
        RESOLVED = 'resolved', 'Default stage and calibration per pollutant'
        EXPANDED = 'expanded', 'All stages and calibrations per pollutant'

    start_date = forms.DateField(required=True)
    end_date = forms.DateField(required=True)
    scope = forms.ChoiceField(choices=Scope.choices, required=False, initial=Scope.RESOLVED)

    MAX_EXPORT_RANGE = timedelta(days=180)

    def __init__(self, *args, **kwargs):
        self.max_export_range = kwargs.pop('max_export_range', self.MAX_EXPORT_RANGE)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if not start_date or not end_date:
            return cleaned_data  # Field-specific errors will already be raised

        if start_date > end_date:
            raise forms.ValidationError('Start date must be on or before end date.')

        if end_date - start_date > self.max_export_range:
            raise forms.ValidationError(f'Maximum export range is {self.max_export_range} days.')

        return cleaned_data


class MonitorAtForm(forms.Form):
    timestamp = forms.DateTimeField(required=True)
    bbox = forms.CharField(required=False)

    def clean_timestamp(self):
        value = self.cleaned_data.get('timestamp')
        if value is not None and timezone.is_naive(value):
            value = make_aware(value, tz=settings.DEFAULT_TIMEZONE)
        return value

    def clean_bbox(self):
        value = self.cleaned_data.get('bbox')
        if not value:
            return None

        parts = value.split(',')
        if len(parts) != 4:
            raise forms.ValidationError('bbox must be "west,south,east,north"')

        try:
            return tuple(float(p) for p in parts)
        except ValueError:
            raise forms.ValidationError('bbox values must be numbers')
