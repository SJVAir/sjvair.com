from datetime import timedelta

from django import forms
from django.contrib.admin.widgets import AdminDateWidget
from django.contrib.gis.geos import Point

from django_recaptcha.widgets import ReCaptchaV2Checkbox


class DateRangeForm(forms.Form):
    timestamp__gte = forms.DateField(label='Start Date', required=True, widget=AdminDateWidget)
    timestamp__lte = forms.DateField(label='End Date', required=True, widget=AdminDateWidget)

    # def clean_end_date(self):
    #     # We want the date range to be inclusive for database
    #     # lookups, so add one day to the end date.
    #     return self.cleaned_data['end_date'] + timedelta(days=1)


class LatLonForm(forms.Form):
    latitude = forms.FloatField(min_value=-90, max_value=90, required=True)
    longitude = forms.FloatField(min_value=-180, max_value=180, required=True)

    @property
    def point(self):
        assert self.is_valid()
        data = self.cleaned_data
        return Point(data['longitude'], data['latitude'], srid=4326)


class VisibleReCaptchaV2Checkbox(ReCaptchaV2Checkbox):
    '''
    django-recaptcha marks its checkbox widget `input_type = "hidden"`, which
    makes Django treat the field as hidden: it renders once in a template's
    `form.hidden_fields` loop and again wherever the field is placed.
    '''
    input_type = None
