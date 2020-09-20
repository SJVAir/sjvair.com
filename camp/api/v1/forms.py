import re

from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

COLOR_RE = re.compile('^([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')
color_validator = RegexValidator(COLOR_RE, _('Enter a valid color.'), 'invalid')


class MarkerForm(forms.Form):
    shape = forms.ChoiceField(choices=[
        (x, x) for x in ('square', 'circle')
        ], initial='circle', required=False)
    fill_color = forms.CharField(validators=[color_validator], initial='777', required=False)
    border_color = forms.CharField(validators=[color_validator], initial='000', required=False)
    border_size = forms.IntegerField(initial=0, required=False)

    def get_defaults(self):
        return {key: field.initial for key, field in self.fields.items()}

    def get_data(self):
        data = self.get_defaults()
        if self.is_valid():
            for key, value in self.cleaned_data.items():
                if value:
                    data[key] = value
        return data
