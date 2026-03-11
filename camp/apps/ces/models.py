from django.db import models
from django.utils.translation import gettext_lazy as _

from camp.apps.ces.querysets import CESManager


class DACCategory(models.IntegerChoices):
    TOP_CES_SCORE = 1, _('Top 25% CES overall score')
    TOP_POLLUTION = 2, _('Top 5% pollution burden (no overall score)')
    PRIOR_DAC = 3, _('Designated under 2017 DAC list')
    TRIBAL_LAND = 4, _('Federally recognized Tribal land')


class CESRecord(models.Model):
    """
    Abstract base for all CalEnviroScreen versions.

    Each concrete record corresponds to exactly one Boundary (census tract
    at a specific vintage). The boundary FK encodes both the tract identity
    (via boundary.region) and the census year (via boundary.version).
    """
    boundary = models.OneToOneField(
        'regions.Boundary',
        on_delete=models.CASCADE,
        related_name='%(class)s',
    )
    population = models.IntegerField(_('Total Population'), null=True)

    # Composite CalEnviroScreen score
    ci_score = models.FloatField(_('CES Score'), null=True)
    ci_score_p = models.FloatField(_('CES Score Percentile'), null=True)

    # SB535 Disadvantaged Community designation for this CES version
    dac_sb535 = models.BooleanField(_('SB535 DAC'), null=True)
    dac_category = models.IntegerField(
        _('DAC Category'),
        null=True, blank=True,
        choices=DACCategory.choices,
    )

    objects = CESManager()

    class Meta:
        abstract = True

    @property
    def region(self):
        return self.boundary.region

    @property
    def census_year(self):
        return self.boundary.version

    @property
    def tract(self):
        return self.boundary.region.external_id

    def __str__(self):
        return f'{self.__class__.__name__} — {self.tract} ({self.census_year})'


class CES4(CESRecord):
    """
    CalEnviroScreen 4.0 (2021), keyed to both 2010 and 2020 census tract
    boundaries. 2010-vintage records use original CES4 scores; 2020-vintage
    records are area-weighted crosswalks from 2010 tracts.

    Percentiles are California-wide as published by OEHHA.
    """

    # --- Pollution Burden ---
    pollution = models.FloatField(_('Pollution Burden Score'), null=True)
    pollution_s = models.FloatField(_('Pollution Burden Score (scaled)'), null=True)
    pollution_p = models.FloatField(_('Pollution Burden Percentile'), null=True)

    pol_ozone = models.FloatField(_('Ozone'), null=True)
    pol_ozone_p = models.FloatField(_('Ozone Percentile'), null=True)
    pol_pm = models.FloatField(_('PM2.5'), null=True)
    pol_pm_p = models.FloatField(_('PM2.5 Percentile'), null=True)
    pol_diesel = models.FloatField(_('Diesel PM'), null=True)
    pol_diesel_p = models.FloatField(_('Diesel PM Percentile'), null=True)
    pol_pest = models.FloatField(_('Pesticides'), null=True)
    pol_pest_p = models.FloatField(_('Pesticides Percentile'), null=True)
    pol_rsei_haz = models.FloatField(_('Toxic Releases (RSEI)'), null=True)
    pol_rsei_haz_p = models.FloatField(_('Toxic Releases Percentile'), null=True)
    pol_traffic = models.FloatField(_('Traffic'), null=True)
    pol_traffic_p = models.FloatField(_('Traffic Percentile'), null=True)
    pol_drink = models.FloatField(_('Drinking Water Contaminants'), null=True)
    pol_drink_p = models.FloatField(_('Drinking Water Contaminants Percentile'), null=True)
    pol_haz = models.FloatField(_('Hazardous Waste'), null=True)
    pol_haz_p = models.FloatField(_('Hazardous Waste Percentile'), null=True)
    pol_lead = models.FloatField(_('Lead'), null=True)
    pol_lead_p = models.FloatField(_('Lead Percentile'), null=True)
    pol_cleanups = models.FloatField(_('Cleanup Sites'), null=True)
    pol_cleanups_p = models.FloatField(_('Cleanup Sites Percentile'), null=True)
    pol_gwthreats = models.FloatField(_('Groundwater Threats'), null=True)
    pol_gwthreats_p = models.FloatField(_('Groundwater Threats Percentile'), null=True)
    pol_iwb = models.FloatField(_('Impaired Water Bodies'), null=True)
    pol_iwb_p = models.FloatField(_('Impaired Water Bodies Percentile'), null=True)
    pol_swis = models.FloatField(_('Solid Waste Sites'), null=True)
    pol_swis_p = models.FloatField(_('Solid Waste Sites Percentile'), null=True)

    # --- Population Characteristics ---
    popchar = models.FloatField(_('Population Characteristics Score'), null=True)
    popchar_s = models.FloatField(_('Population Characteristics Score (scaled)'), null=True)
    popchar_p = models.FloatField(_('Population Characteristics Percentile'), null=True)

    char_asthma = models.FloatField(_('Asthma'), null=True)
    char_asthma_p = models.FloatField(_('Asthma Percentile'), null=True)
    char_cvd = models.FloatField(_('Cardiovascular Disease'), null=True)
    char_cvd_p = models.FloatField(_('Cardiovascular Disease Percentile'), null=True)
    char_lbw = models.FloatField(_('Low Birth Weight'), null=True)
    char_lbw_p = models.FloatField(_('Low Birth Weight Percentile'), null=True)
    char_edu = models.FloatField(_('Educational Attainment'), null=True)
    char_edu_p = models.FloatField(_('Educational Attainment Percentile'), null=True)
    char_ling = models.FloatField(_('Linguistic Isolation'), null=True)
    char_ling_p = models.FloatField(_('Linguistic Isolation Percentile'), null=True)
    char_pov = models.FloatField(_('Poverty'), null=True)
    char_pov_p = models.FloatField(_('Poverty Percentile'), null=True)
    char_unemp = models.FloatField(_('Unemployment'), null=True)
    char_unemp_p = models.FloatField(_('Unemployment Percentile'), null=True)
    char_housingb = models.FloatField(_('Housing Burden'), null=True)
    char_housingb_p = models.FloatField(_('Housing Burden Percentile'), null=True)

    # --- Demographics ---
    pop_under_10 = models.IntegerField(_('Population Under 10'), null=True)
    pop_10_64 = models.IntegerField(_('Population 10–64'), null=True)
    pop_65_plus = models.IntegerField(_('Population 65+'), null=True)
    pop_hispanic = models.IntegerField(_('Hispanic Population'), null=True)
    pop_white = models.IntegerField(_('White Population'), null=True)
    pop_black = models.IntegerField(_('Black or African American Population'), null=True)
    pop_native = models.IntegerField(_('American Indian and Alaska Native Population'), null=True)
    pop_aapi = models.IntegerField(_('Asian American and Pacific Islander Population'), null=True)
    pop_other = models.IntegerField(_('Other or Multiple Races Population'), null=True)

    class Meta(CESRecord.Meta):
        verbose_name = _('CalEnviroScreen 4.0')
        verbose_name_plural = _('CalEnviroScreen 4.0 Records')
        ordering = ['boundary__region__external_id']
