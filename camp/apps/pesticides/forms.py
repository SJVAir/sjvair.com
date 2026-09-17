from django import forms
from django.utils.translation import gettext_lazy as _

from camp.apps.pesticides.models import Chemical, PesticideUse
from camp.apps.regions.models import Region

BOOL_CHOICES = [('', _('Any')), ('true', _('Yes')), ('false', _('No'))]
RADIUS_CHOICES = [('1', '1'), ('3', '3'), ('5', '5')]


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


class RecordsFilterForm(forms.Form):
    start = forms.DateField(label=_('Start date'), required=False)
    end = forms.DateField(label=_('End date'), required=False)
    county = forms.ChoiceField(label=_('County'), required=False, choices=[('', _('Any'))])
    method = forms.ChoiceField(
        label=_('Method'),
        required=False,
        choices=[('', _('Any'))] + list(PesticideUse.AerialGround.choices),
    )

    # Carried as hidden inputs -- set by the section map / entity pages, not
    # edited directly in this form.
    region = forms.CharField(required=False, widget=forms.HiddenInput)
    section = forms.CharField(required=False, widget=forms.HiddenInput)
    chemical = forms.CharField(required=False, widget=forms.HiddenInput)
    product = forms.CharField(required=False, widget=forms.HiddenInput)
    commodity = forms.CharField(required=False, widget=forms.HiddenInput)
    lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    lng = forms.FloatField(required=False, widget=forms.HiddenInput)
    radius = forms.ChoiceField(required=False, choices=RADIUS_CHOICES, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        counties = Region.objects.filter(type=Region.Type.COUNTY).order_by('name').values_list('slug', 'name')
        self.fields['county'].choices = [('', _('Any'))] + list(counties)
