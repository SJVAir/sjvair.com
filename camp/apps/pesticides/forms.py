from django import forms
from django.utils.translation import gettext_lazy as _

from camp.apps.pesticides.models import Chemical

BOOL_CHOICES = [('', _('Any')), ('true', _('Yes')), ('false', _('No'))]


class SearchForm(forms.Form):
    q = forms.CharField(label=_('Search'), required=False, max_length=128)

    def bool_value(self, name):
        value = self.cleaned_data.get(name)
        return {'true': True, 'false': False}.get(value)


class ChemicalFilterForm(SearchForm):
    category = forms.MultipleChoiceField(
        label=_('Category'),
        required=False,
        choices=Chemical.Category.choices,
        widget=forms.CheckboxSelectMultiple,
    )
    iarc_group = forms.ChoiceField(
        label=_('IARC group'),
        required=False,
        choices=[('', _('Any'))] + list(Chemical.IARCGroup.choices),
    )


class ProductFilterForm(SearchForm):
    fumigant = forms.ChoiceField(label=_('Fumigant'), required=False, choices=BOOL_CHOICES)
    california_restricted = forms.ChoiceField(label=_('California restricted'), required=False, choices=BOOL_CHOICES)


class CommodityFilterForm(SearchForm):
    pass
