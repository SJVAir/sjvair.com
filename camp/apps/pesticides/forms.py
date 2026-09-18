from django import forms
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from camp.apps.pesticides.models import Chemical, PesticideNotice, PesticideUse
from camp.apps.pesticides.places import RADIUS_CHOICES as RADIUS_MILES
from camp.apps.regions.models import Region

BOOL_CHOICES = [('', _('Any')), ('true', _('Yes')), ('false', _('No'))]
# The allowed radii live in places.RADIUS_CHOICES; these are just their
# form-field (string) spellings.
RADIUS_CHOICES = [(str(miles), str(miles)) for miles in RADIUS_MILES]


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


class NoticeFilterForm(forms.Form):
    county = forms.ChoiceField(label=_('County'), required=False, choices=[('', _('Any'))])
    method = forms.ChoiceField(label=_('Method'), required=False, choices=[('', _('Any'))])
    past = forms.BooleanField(label=_('Archive'), required=False)
    month = forms.IntegerField(required=False, min_value=1, max_value=12)
    # Narrows the archive to a year. Bounded so an out-of-range value is a
    # validation error (and so no filter) rather than a ValueError out of
    # `datetime()`. Named `archive_year` to keep it off the site-wide
    # `?year=` picker, which means something else entirely.
    archive_year = forms.IntegerField(required=False, min_value=1900, max_value=2100)

    # Carried as hidden inputs -- set by entity pages / the section map, not
    # edited directly in this form.
    chemical = forms.CharField(required=False, widget=forms.HiddenInput)
    product = forms.CharField(required=False, widget=forms.HiddenInput)
    region = forms.CharField(required=False, widget=forms.HiddenInput)
    section = forms.CharField(required=False, widget=forms.HiddenInput)
    lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    lng = forms.FloatField(required=False, widget=forms.HiddenInput)
    radius = forms.ChoiceField(required=False, choices=RADIUS_CHOICES, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        counties = Region.objects.filter(type=Region.Type.COUNTY).order_by('name').values_list('slug', 'name')
        self.fields['county'].choices = [('', _('Any'))] + list(counties)

        methods = cache.get('pesticides:notice-methods')
        if methods is None:
            methods = list(
                PesticideNotice.objects
                .exclude(application_method='')
                .order_by()
                .values_list('application_method', flat=True)
                .distinct()
            )
            cache.set('pesticides:notice-methods', methods, 60 * 60)
        self.fields['method'].choices = [('', _('Any'))] + [(method, method) for method in sorted(methods)]


class RecordsFilterForm(forms.Form):
    start = forms.DateField(label=_('Start date'), required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}, format='%Y-%m-%d'))
    end = forms.DateField(label=_('End date'), required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}, format='%Y-%m-%d'))
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
