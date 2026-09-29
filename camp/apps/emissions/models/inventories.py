from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class CountyInventory(models.Model):
    """
    One county's CARB emission inventory (CEPAM) for one emission inventory
    code (EIC) and year: every source, not only permitted facilities, in
    tons/day (annual average) as CARB publishes it. Only the inventory's base
    year is an inventory; other years are CARB's back-casts and projections.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.CountyInventory'))

    class SourceType(models.TextChoices):
        STATIONARY = 'stationary', _('Stationary')
        AREAWIDE = 'areawide', _('Areawide')
        MOBILE = 'mobile', _('Mobile')
        NATURAL = 'natural', _('Natural')

    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.CASCADE, related_name='+')
    year = models.IntegerField(_('Year'))
    inventory = models.CharField(_('Inventory'), max_length=32)
    source_type = models.CharField(_('Source type'), max_length=16, choices=SourceType.choices, db_index=True)
    eic = models.CharField(_('EIC'), max_length=20)
    summary_name = models.CharField(_('Summary category'), max_length=128, blank=True)
    source_name = models.CharField(_('Source'), max_length=128, blank=True)
    material_name = models.CharField(_('Material'), max_length=128, blank=True)
    subcategory_name = models.CharField(_('Subcategory'), max_length=128, blank=True)

    tog = models.FloatField(_('TOG (tons/day)'), null=True)
    rog = models.FloatField(_('ROG (tons/day)'), null=True)
    co = models.FloatField(_('CO (tons/day)'), null=True)
    nox = models.FloatField(_('NOx (tons/day)'), null=True)
    sox = models.FloatField(_('SOx (tons/day)'), null=True)
    pm = models.FloatField(_('Total PM (tons/day)'), null=True)
    pm10 = models.FloatField(_('PM10 (tons/day)'), null=True)
    pm25 = models.FloatField(_('PM2.5 (tons/day)'), null=True)

    class Meta:
        unique_together = [('county', 'year', 'inventory', 'eic')]
        verbose_name_plural = 'county inventories'

    def __str__(self):
        return f'{self.eic} {self.county} {self.year}'


class CountyNEI(models.Model):
    """
    One county's emissions of one pollutant in EPA's National Emissions
    Inventory for one NEI year, by EPA sector (subsector blank) or, for the
    livestock-waste sector, by animal type (the nonpoint file's SCC level 3,
    "Dairy Cattle Waste"). Every source, not only permitted facilities; EPA
    and CARB model estimates in tons per year, not measurements. Ammonia only
    for now: CARB's own county inventory (CEPAM) publishes none.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.CountyNEI'))
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.CASCADE, related_name='+')
    year = models.IntegerField(_('NEI year'))
    pollutant = models.CharField(_('Pollutant code'), max_length=8, default='NH3')
    sector = models.CharField(_('EPA sector'), max_length=128)
    subsector = models.CharField(_('Subsector'), max_length=128, blank=True)
    tons = models.FloatField(_('Emissions (tons/yr)'))

    class Meta:
        unique_together = [('county', 'year', 'pollutant', 'sector', 'subsector')]
        verbose_name = 'county NEI row'
        verbose_name_plural = 'county NEI rows'

    def __str__(self):
        return f'{self.county} {self.year} {self.pollutant} {self.sector}{" / " + self.subsector if self.subsector else ""}'
