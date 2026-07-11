from django.db import models
from django.utils.translation import gettext_lazy as _
from django_sqids import SqidsField, shuffle_alphabet

from camp.apps.ces.querysets import CESManager


class DACCategory(models.IntegerChoices):
    TOP_CES_SCORE = 1, _('Top 25% CES overall score')
    TOP_POLLUTION = 2, _('Top 5% pollution burden (no overall score)')
    PRIOR_DAC = 3, _('Carried over from prior DAC designation')
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

    # New models in this project use sqids for their external identifier
    # (see CLAUDE.md Key Conventions).
    sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES4'))

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


class CES5(CESRecord):
    """
    CalEnviroScreen 5.0 (2026), keyed to 2020 census tract boundaries only.
    Unlike CES4, CES5 is natively 2020-vintage — no crosswalk is needed.

    Percentiles are California-wide as published by OEHHA. Demographic
    fields are percentages (unlike CES4's raw population counts), suffixed
    `_pct` to make that distinction impossible to miss.
    """

    # New models in this project use sqids for their external identifier
    # (see CLAUDE.md Key Conventions). CES4 predates this convention.
    sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES5'))

    # --- Tract metadata (new in CES5) ---
    zipcode = models.IntegerField(_('ZIP Code'), null=True)
    approx_loc = models.CharField(_('Approximate Location'), max_length=100, null=True, blank=True)
    county = models.CharField(_('County'), max_length=100, null=True, blank=True)
    region_name = models.CharField(_('CalEnviroScreen Region'), max_length=100, null=True, blank=True)

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
    pol_lead = models.FloatField(_("Child's Lead Risk from Housing"), null=True)
    pol_lead_p = models.FloatField(_("Child's Lead Risk from Housing Percentile"), null=True)
    pol_cleanups = models.FloatField(_('Cleanup Sites'), null=True)
    pol_cleanups_p = models.FloatField(_('Cleanup Sites Percentile'), null=True)
    pol_gwthreats = models.FloatField(_('Groundwater Threats'), null=True)
    pol_gwthreats_p = models.FloatField(_('Groundwater Threats Percentile'), null=True)
    pol_haz = models.FloatField(_('Hazardous Waste'), null=True)
    pol_haz_p = models.FloatField(_('Hazardous Waste Percentile'), null=True)
    pol_iwb = models.FloatField(_('Impaired Water Bodies'), null=True)
    pol_iwb_p = models.FloatField(_('Impaired Water Bodies Percentile'), null=True)
    pol_small_ats = models.FloatField(_('Small Air Toxic Sites'), null=True)
    pol_small_ats_p = models.FloatField(_('Small Air Toxic Sites Percentile'), null=True)
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
    char_diabetes = models.FloatField(_('Diabetes Prevalence'), null=True)
    char_diabetes_p = models.FloatField(_('Diabetes Prevalence Percentile'), null=True)
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

    # --- Demographics (percentages, unlike CES4's raw counts) ---
    pop_under_10_pct = models.FloatField(_('Population Under 10 (%)'), null=True)
    pop_10_64_pct = models.FloatField(_('Population 10–64 (%)'), null=True)
    pop_65_plus_pct = models.FloatField(_('Population 65+ (%)'), null=True)
    pop_hispanic_pct = models.FloatField(_('Hispanic/Latino Population (%)'), null=True)
    pop_white_pct = models.FloatField(_('White Population (%)'), null=True)
    pop_black_pct = models.FloatField(_('Black or African American Population (%)'), null=True)
    pop_native_pct = models.FloatField(_('American Indian and Alaska Native Population (%)'), null=True)
    pop_asian_pct = models.FloatField(_('Asian Population (%)'), null=True)
    pop_pacisl_pct = models.FloatField(_('Pacific Islander Population (%)'), null=True)
    pop_other_pct = models.FloatField(_('Other or Multiple Races Population (%)'), null=True)

    class Meta(CESRecord.Meta):
        verbose_name = _('CalEnviroScreen 5.0')
        verbose_name_plural = _('CalEnviroScreen 5.0 Records')
        ordering = ['boundary__region__external_id']
