from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class GHGReport(models.Model):
    """
    One large emitter's reported greenhouse gases for one year, from EPA's
    Greenhouse Gas Reporting Program (GHGRP) or CARB's Mandatory GHG
    Reporting (MRR). Metric tons. `co2e` is the emitter's own non-biogenic
    total; biogenic CO2 is kept apart, never added in. `ch4` and `n2o` are
    tons of the gas itself, not CO2e. Matched to a CEIDARS facility when we
    can say so with confidence; otherwise it still has a county, and county
    pages show it as an unmatched reporter.
    """

    class Program(models.TextChoices):
        GHGRP = 'ghgrp', _('EPA GHGRP')
        MRR = 'mrr', _('CARB MRR')

    class MatchMethod(models.TextChoices):
        FRS = 'frs', _('FRS air program id')
        CROSSWALK = 'crosswalk', _('Hand-curated crosswalk')
        AUTO = 'auto', _('Name and place')
        NONE = '', _('Unmatched')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.GHGReport'))
    program = models.CharField(_('Program'), max_length=8, choices=Program.choices, db_index=True)
    # GHGRP facility_id or the MRR "ARB ID": the program's own key, as text.
    external_id = models.CharField(_('External id'), max_length=20)
    year = models.IntegerField(_('Year'), db_index=True)
    facility = models.ForeignKey(
        'emissions.Facility', verbose_name=_('Facility'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='ghg_reports',
    )
    # GHGRP: from county_fips. MRR: the matched facility's county, else the
    # county containing the reported ZIP. Null only when neither resolves.
    county = models.ForeignKey(
        'regions.Region', verbose_name=_('County'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    name = models.CharField(_('Name'), max_length=128)
    city = models.CharField(_('City'), max_length=64, blank=True)
    zipcode = models.CharField(_('ZIP code'), max_length=10, blank=True)
    naics = models.CharField(_('NAICS'), max_length=8, blank=True)
    # GHGRP facility_types ("Direct Emitter") / MRR Industry Sector ("Refinery").
    sector = models.CharField(_('Sector'), max_length=128, blank=True)
    subparts = models.CharField(_('Subparts'), max_length=128, blank=True)
    co2e = models.FloatField(_('CO2e (metric tons)'))
    co2e_biogenic = models.FloatField(_('Biogenic CO2 (metric tons)'), null=True, blank=True)
    ch4 = models.FloatField(_('CH4 (metric tons)'), null=True, blank=True)
    n2o = models.FloatField(_('N2O (metric tons)'), null=True, blank=True)
    point = models.PointField(_('Point'), null=True, blank=True)
    frs_id = models.CharField(_('FRS registry id'), max_length=12, blank=True)
    # MRR oil & gas production is reported per basin, not per site.
    basin_wide = models.BooleanField(_('Basin-wide'), default=False)
    match_method = models.CharField(_('Match method'), max_length=10, choices=MatchMethod.choices, blank=True, default='')

    class Meta:
        unique_together = [('program', 'external_id', 'year')]
        ordering = ['-co2e']
        verbose_name = _('GHG report')

    def __str__(self):
        return f'{self.get_program_display()} {self.year}: {self.name}'

    @property
    def source_url(self):
        if self.program == self.Program.GHGRP:
            return f'https://ghgdata.epa.gov/ghgp/service/facilityDetail/{self.year}?id={self.external_id}&et=undefined'
        return 'https://ww2.arb.ca.gov/mrr-data'
