from django.db import models
from django.utils.translation import gettext_lazy as _

from camp.apps.ces.querysets import CESQuerySet


class DACCategory(models.IntegerChoices):
    TOP_CES_SCORE    = 1, _('Top 25% CES overall score')
    TOP_POLLUTION    = 2, _('Top 5% pollution burden (no overall score)')
    PRIOR_DAC        = 3, _('Designated under 2017 DAC list')
    TRIBAL_LAND      = 4, _('Federally recognized Tribal land')


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
    population = models.IntegerField(null=True)

    # Composite CalEnviroScreen score
    ci_score   = models.FloatField(null=True, verbose_name='CES Score')
    ci_score_p = models.FloatField(null=True, verbose_name='CES Score Percentile')

    # SB535 Disadvantaged Community designation for this CES version
    dac_sb535    = models.BooleanField(null=True, verbose_name='SB535 DAC')
    dac_category = models.IntegerField(
        null=True, blank=True,
        choices=DACCategory.choices,
        verbose_name='DAC Category',
    )

    objects = CESQuerySet.as_manager()

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
    pollution   = models.FloatField(null=True, verbose_name='Pollution Burden Score')
    pollution_s = models.FloatField(null=True, verbose_name='Pollution Burden Score (scaled)')
    pollution_p = models.FloatField(null=True, verbose_name='Pollution Burden Percentile')

    pol_ozone     = models.FloatField(null=True, verbose_name='Ozone')
    pol_ozone_p   = models.FloatField(null=True, verbose_name='Ozone Percentile')
    pol_pm        = models.FloatField(null=True, verbose_name='PM2.5')
    pol_pm_p      = models.FloatField(null=True, verbose_name='PM2.5 Percentile')
    pol_diesel    = models.FloatField(null=True, verbose_name='Diesel PM')
    pol_diesel_p  = models.FloatField(null=True, verbose_name='Diesel PM Percentile')
    pol_pest      = models.FloatField(null=True, verbose_name='Pesticides')
    pol_pest_p    = models.FloatField(null=True, verbose_name='Pesticides Percentile')
    pol_rsei_haz  = models.FloatField(null=True, verbose_name='Toxic Releases (RSEI)')
    pol_rsei_haz_p= models.FloatField(null=True, verbose_name='Toxic Releases Percentile')
    pol_traffic   = models.FloatField(null=True, verbose_name='Traffic')
    pol_traffic_p = models.FloatField(null=True, verbose_name='Traffic Percentile')
    pol_drink     = models.FloatField(null=True, verbose_name='Drinking Water')
    pol_drink_p   = models.FloatField(null=True, verbose_name='Drinking Water Percentile')
    pol_haz       = models.FloatField(null=True, verbose_name='Hazardous Waste')
    pol_haz_p     = models.FloatField(null=True, verbose_name='Hazardous Waste Percentile')
    pol_lead      = models.FloatField(null=True, verbose_name='Lead')
    pol_lead_p    = models.FloatField(null=True, verbose_name='Lead Percentile')
    pol_cleanups  = models.FloatField(null=True, verbose_name='Cleanup Sites')
    pol_cleanups_p= models.FloatField(null=True, verbose_name='Cleanup Sites Percentile')
    pol_gwthreats = models.FloatField(null=True, verbose_name='Groundwater Threats')
    pol_gwthreats_p = models.FloatField(null=True, verbose_name='Groundwater Threats Percentile')
    pol_iwb       = models.FloatField(null=True, verbose_name='Impaired Water Bodies')
    pol_iwb_p     = models.FloatField(null=True, verbose_name='Impaired Water Bodies Percentile')
    pol_swis      = models.FloatField(null=True, verbose_name='Solid Waste Sites')
    pol_swis_p    = models.FloatField(null=True, verbose_name='Solid Waste Sites Percentile')

    # --- Population Characteristics ---
    popchar   = models.FloatField(null=True, verbose_name='Population Characteristics Score')
    popchar_s = models.FloatField(null=True, verbose_name='Population Characteristics Score (scaled)')
    popchar_p = models.FloatField(null=True, verbose_name='Population Characteristics Percentile')

    char_asthma   = models.FloatField(null=True, verbose_name='Asthma')
    char_asthma_p = models.FloatField(null=True, verbose_name='Asthma Percentile')
    char_cvd      = models.FloatField(null=True, verbose_name='Cardiovascular Disease')
    char_cvd_p    = models.FloatField(null=True, verbose_name='Cardiovascular Disease Percentile')
    char_lbw      = models.FloatField(null=True, verbose_name='Low Birth Weight')
    char_lbw_p    = models.FloatField(null=True, verbose_name='Low Birth Weight Percentile')
    char_edu      = models.FloatField(null=True, verbose_name='Educational Attainment')
    char_edu_p    = models.FloatField(null=True, verbose_name='Educational Attainment Percentile')
    char_ling     = models.FloatField(null=True, verbose_name='Linguistic Isolation')
    char_ling_p   = models.FloatField(null=True, verbose_name='Linguistic Isolation Percentile')
    char_pov      = models.FloatField(null=True, verbose_name='Poverty')
    char_pov_p    = models.FloatField(null=True, verbose_name='Poverty Percentile')
    char_unemp    = models.FloatField(null=True, verbose_name='Unemployment')
    char_unemp_p  = models.FloatField(null=True, verbose_name='Unemployment Percentile')
    char_housingb   = models.FloatField(null=True, verbose_name='Housing Burden')
    char_housingb_p = models.FloatField(null=True, verbose_name='Housing Burden Percentile')

    # --- Demographics ---
    pop_hispanic = models.IntegerField(null=True, verbose_name='Hispanic Population')
    pop_white    = models.IntegerField(null=True, verbose_name='White Population')
    pop_black    = models.IntegerField(null=True, verbose_name='Black Population')
    pop_native   = models.IntegerField(null=True, verbose_name='Native American Population')
    pop_asian    = models.IntegerField(null=True, verbose_name='Asian American Population')
    pop_other    = models.IntegerField(null=True, verbose_name='Other/Mixed Population')

    class Meta(CESRecord.Meta):
        verbose_name = 'CalEnviroScreen 4.0'
        verbose_name_plural = 'CalEnviroScreen 4.0 Records'
