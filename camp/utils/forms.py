from datetime import timedelta

from django import forms
from django.contrib.admin.widgets import AdminDateWidget


class DateRangeForm(forms.Form):
    timestamp__gte = forms.DateField(label='Start Date', required=True, widget=AdminDateWidget)
    timestamp__lte = forms.DateField(label='End Date', required=True, widget=AdminDateWidget)

    # def clean_end_date(self):
    #     # We want the date range to be inclusive for database
    #     # lookups, so add one day to the end date.
    #     return self.cleaned_data['end_date'] + timedelta(days=1)
