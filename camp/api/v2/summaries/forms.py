from datetime import timedelta

from django import forms

from camp.api.v2.forms import BboxField
from camp.apps.summaries.models import BaseSummary


class BulkMonitorSummaryForm(forms.Form):
    """`start`/`end` are inclusive dates. The span is capped per resolution so a
    single request can't page through an unbounded number of rows (hourly and
    daily are the only resolutions dense enough to need it)."""

    MAX_RANGE = {
        BaseSummary.Resolution.HOURLY: timedelta(days=31),
        BaseSummary.Resolution.DAILY: timedelta(days=366),
    }

    start = forms.DateField(required=True)
    end = forms.DateField(required=True)
    bbox = BboxField()

    def __init__(self, *args, resolution=None, **kwargs):
        self.resolution = resolution
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start')
        end = cleaned_data.get('end')

        if not start or not end:
            return cleaned_data  # Field-specific errors will already be raised

        if start > end:
            raise forms.ValidationError('start must be on or before end.')

        try:
            cleaned_data['end_exclusive'] = end + timedelta(days=1)
        except OverflowError:
            raise forms.ValidationError('end is out of range.')

        max_range = self.MAX_RANGE.get(self.resolution)
        if max_range is not None and end - start > max_range:
            raise forms.ValidationError(
                f'Maximum date range for {self.resolution} resolution is {max_range.days} days.'
            )

        return cleaned_data
