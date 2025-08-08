from django import forms
from datetime import timedelta
from django.utils import timezone


class EntryExportForm(forms.Form):
    start_date = forms.DateField(required=True)
    end_date = forms.DateField(required=True)

    MAX_EXPORT_RANGE = timedelta(days=180)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if not start_date or not end_date:
            return cleaned_data  # Field-specific errors will already be raised

        if start_date >= end_date:
            raise forms.ValidationError('Start date must be before end date.')

        if end_date - start_date > self.MAX_EXPORT_RANGE:
            raise forms.ValidationError('Maximum export range is 180 days.')

        return cleaned_data
