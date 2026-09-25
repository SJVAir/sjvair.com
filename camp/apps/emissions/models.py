from django.contrib.gis.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils import geocode as _geocode


# SIC codes that CEIDARS excludes via the "all_fac=C" parameter -- gas stations,
# newspapers, print shops, dry cleaners, and autobody shops. These are minor
# permitted sources whose emissions are aggregated at the county level in CARB's
# areawide inventory rather than individually attributed.
MINOR_SOURCE_SIC_CODES = frozenset([
    2711,  # Newspapers
    2752,  # Commercial printing, lithographic
    5541,  # Gasoline service stations
    7216,  # Dry cleaning plants
    7532,  # Top, body & upholstery repair shops
    7538,  # Automotive repair shops, NEC
])


class FacilityQuerySet(models.QuerySet):
    def major_sources(self):
        return self.exclude(sic_code__in=MINOR_SOURCE_SIC_CODES)

    def minor_sources(self):
        return self.filter(sic_code__in=MINOR_SOURCE_SIC_CODES)


class FacilityManager(models.Manager):
    def get_queryset(self):
        return (
            FacilityQuerySet(self.model, using=self._db)
            .select_related('county', 'zipcode', 'city', 'air_district')
        )

    def major_sources(self):
        return self.get_queryset().major_sources()

    def minor_sources(self):
        return self.get_queryset().minor_sources()


class Facility(TimeStampedModel):
    """A permitted stationary source in CARB's CEIDARS facility inventory."""

    # Plain-language industry groups over SIC codes; the SIC -> sector map is
    # camp/apps/emissions/sectors.py. Adding one: a choice here, its codes
    # there (migration is choices-only), then `assign_sectors`.
    class Sector(models.TextChoices):
        DAIRIES_LIVESTOCK = 'dairies-livestock', _('Dairies & livestock')
        FARMS = 'farms', _('Farms & orchards')
        CROP_PROCESSING = 'crop-processing', _('Crop processing & cotton gins')
        OIL_GAS = 'oil-gas', _('Oil & gas production')
        MINING = 'mining', _('Mining & quarries')
        GLASS = 'glass', _('Glass manufacturing')
        CEMENT_MINERALS = 'cement-minerals', _('Cement, concrete & minerals')
        REFINING_FUELS = 'refining-fuels', _('Refineries, fuel terminals & pipelines')
        WINERIES_BEVERAGES = 'wineries-beverages', _('Wineries & beverages')
        FOOD_PROCESSING = 'food-processing', _('Food processing')
        CHEMICALS = 'chemicals', _('Chemicals & fertilizers')
        POWER_PLANTS = 'power-plants', _('Power plants')
        WASTE_WATER = 'waste-water', _('Waste, water & recycling')
        TELECOM = 'telecom', _('Telecommunications')
        TRANSPORTATION = 'transportation', _('Transportation & warehousing')
        GAS_STATIONS = 'gas-stations', _('Gas stations')
        AUTO_REPAIR = 'auto-repair', _('Auto body & repair')
        DRY_CLEANERS = 'dry-cleaners', _('Dry cleaners')
        MANUFACTURING = 'manufacturing', _('Other manufacturing')
        HOSPITALS_SCHOOLS = 'hospitals-schools', _('Hospitals & schools')
        GOVERNMENT_MILITARY = 'government-military', _('Government & military')
        COMMERCIAL = 'commercial', _('Commercial & services')
        OTHER = 'other', _('Other')

    objects = FacilityManager()
    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Facility'))

    # CARB's county number (alphabetical, 1-58).
    county_code = models.IntegerField(_('County code'))
    # The air district that regulates the facility. Part of its identity:
    # districts assign FACIDs independently, so a FACID is only unique within
    # one. Taken from CARB's DIS code at import, never from the point (which
    # can be missing, or land on the wrong side of a district line).
    air_district = models.ForeignKey(
        'regions.Region',
        verbose_name=_('Air district'),
        on_delete=models.PROTECT,
        related_name='district_facilities',
        limit_choices_to={'type': 'air_district'},
    )
    facid = models.IntegerField(_('Facility ID'))

    # Tracks which import year last wrote the facility metadata (name, address,
    # sic_code, region FKs). Used to prevent older imports from overwriting
    # newer metadata -- emissions records are always upserted regardless.
    metadata_year = models.IntegerField(_('Metadata year'), null=True, blank=True)
    name = models.CharField(_('Name'), max_length=60)
    sic_code = models.IntegerField(_('SIC code'), null=True, blank=True)
    sector = models.CharField(_('Sector'), max_length=32, choices=Sector.choices, default=Sector.OTHER, db_index=True)

    # Raw address fields from CEIDARS -- preserved as-is for reference.
    # City names in particular are noisy (typos, non-city strings, county
    # names) so matching against Region is handled separately via the FKs.
    address = models.JSONField(_('Address'), default=dict, blank=True)

    # Region FKs -- populated at import time from address data.
    # county is always set (the county being imported).
    # zipcode and city may be null for PO Box ZIPs (no ZCTA polygon exists)
    # or unresolvable city strings.
    county = models.ForeignKey(
        'regions.Region',
        verbose_name=_('County'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='county_facilities',
    )
    zipcode = models.ForeignKey(
        'regions.Region',
        verbose_name=_('Zipcode'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='zipcode_facilities',
    )
    city = models.ForeignKey(
        'regions.Region',
        verbose_name=_('City'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='city_facilities',
    )

    point = models.PointField(_('Point'), null=True, blank=True)

    class Meta:
        unique_together = [('county_code', 'air_district', 'facid')]
        verbose_name_plural = 'facilities'

    def __str__(self):
        return f'{self.name} ({self.address.get("city", "")})'

    def get_county(self):
        return self.county.name if self.county_id else None

    def get_city(self):
        return self.city.name if self.city_id else self.address.get('city', '')

    def get_zipcode(self):
        return self.zipcode.name if self.zipcode_id else self.address.get('zipcode', '')

    @property
    def is_minor_source(self):
        return self.sic_code in MINOR_SOURCE_SIC_CODES

    def get_absolute_url(self):
        return reverse('emissions:facility-detail', kwargs={
            'sqid': self.sqid,
            'slug': slugify(self.name) or 'facility',
        })

    def geocode(self):
        """
        Geocodes the facility address, trying Census first then MapTiler.
        Sets self.point on success. Returns True/False. Does not save.
        """
        street = self.address.get('street', '')
        city = self.address.get('city', '')
        zipcode = self.address.get('zipcode', '')
        point = _geocode.resolve(f'{street}, {city}, CA {zipcode}')
        if point:
            self.point = point
            return True
        return False


class EmissionsRecord(TimeStampedModel):
    """One facility's CEIDARS emissions for one inventory year, in tons/yr."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.EmissionsRecord'))
    facility = models.ForeignKey(
        Facility,
        related_name='emissions',
        on_delete=models.CASCADE,
    )
    year = models.IntegerField(_('Year'))

    # Criteria pollutants (tons/yr). CARB's PMT column is total particulate
    # matter; CEIDARS has no facility-level PM2.5.
    tog = models.DecimalField(_('Total organic gases (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    rog = models.DecimalField(_('Reactive organic gases (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    co = models.DecimalField(_('Carbon monoxide (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    nox = models.DecimalField(_('Nitrogen oxides (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    sox = models.DecimalField(_('Sulfur oxides (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm = models.DecimalField(_('Total PM (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm10 = models.DecimalField(_('PM10 (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)

    # Toxics summary (blank for all SJV facilities in current CARB exports; kept, not displayed)
    total_score = models.DecimalField(_('Total toxics score'), max_digits=10, decimal_places=2, null=True, blank=True)
    hra = models.DecimalField(_('Health risk assessment'), max_digits=10, decimal_places=2, null=True, blank=True)
    chindex = models.DecimalField(_('Cancer health index'), max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(_('Acute health index'), max_digits=10, decimal_places=2, null=True, blank=True)

    # Named toxic air contaminants (tons/yr; the explorer shows lbs/yr)
    acetaldehyde = models.DecimalField(_('Acetaldehyde (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    benzene = models.DecimalField(_('Benzene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    butadiene = models.DecimalField(_('1,3-Butadiene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    carbon_tetrachloride = models.DecimalField(_('Carbon tetrachloride (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    chromium_hexavalent = models.DecimalField(_('Chromium hexavalent (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    dichlorobenzene = models.DecimalField(_('para-Dichlorobenzene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    formaldehyde = models.DecimalField(_('Formaldehyde (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    methylene_chloride = models.DecimalField(_('Methylene chloride (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    naphthalene = models.DecimalField(_('Naphthalene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    perchloroethylene = models.DecimalField(_('Perchloroethylene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)

    class Meta:
        unique_together = [('facility', 'year')]
        indexes = [
            models.Index(fields=['year', 'facility']),
        ]

    def __str__(self):
        return f'{self.facility.name} ({self.year})'


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


# CADD's reference code for a count that was reported; every other code
# (2a-2f, 3a-3g) marks one of CARB's estimates or gap fills.
REPORTED_REF_CODE = '1'

# EPA animal units (40 CFR 122, Appendix B): each mature dairy cow, milking or
# dry, counts 1.4; every other head of cattle 1.0.
MATURE_DAIRY_FACTOR = 1.4
OTHER_CATTLE_FACTOR = 1.0
MATURE_DAIRY_FIELDS = ('milk_cows', 'dry_cows')
OTHER_CATTLE_FIELDS = ('old_heifers', 'young_heifers', 'old_calves', 'young_calves', 'beef_cattle')
HERD_FIELDS = MATURE_DAIRY_FIELDS + OTHER_CATTLE_FIELDS


def animal_units(counts):
    """EPA animal units from {herd field: count}; a blank (None) count is unknown and left out."""
    mature = sum(counts.get(field) or 0 for field in MATURE_DAIRY_FIELDS)
    other = sum(counts.get(field) or 0 for field in OTHER_CATTLE_FIELDS)
    return mature * MATURE_DAIRY_FACTOR + other * OTHER_CATTLE_FACTOR


class Dairy(TimeStampedModel):
    """
    A dairy in CARB's California Dairy & Livestock Database (CADD): where it
    is. Its herd by year is DairyHerd, its anaerobic digesters Digester.
    Nothing here is an emission estimate.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Dairy'))
    cadd_id = models.IntegerField(_('CADD ID'), unique=True)
    place_id = models.IntegerField(_('Place ID'))
    name = models.CharField(_('Name'), max_length=128)
    # As CADD gives it: street, city, zipcode.
    address = models.JSONField(_('Address'), default=dict, blank=True)
    point = models.PointField(_('Point'))
    # Resolved from CADD's county name at import.
    county = models.ForeignKey(
        'regions.Region',
        verbose_name=_('County'),
        on_delete=models.PROTECT,
        related_name='dairies',
    )
    water_board = models.CharField(_('Regional water board'), max_length=8, blank=True)
    cadd_version = models.CharField(_('CADD version'), max_length=16)

    class Meta:
        verbose_name_plural = 'dairies'

    def __str__(self):
        return f'{self.name} ({self.address.get("city", "")})'


class DairyHerd(models.Model):
    """One dairy's herd in one year, as CADD counts it. A blank count is unknown, not zero."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DairyHerd'))
    dairy = models.ForeignKey(Dairy, verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='herds')
    year = models.IntegerField(_('Year'))
    milk_cows = models.IntegerField(_('Milk cows'), null=True, blank=True)
    dry_cows = models.IntegerField(_('Dry cows'), null=True, blank=True)
    old_heifers = models.IntegerField(_('Heifers (older)'), null=True, blank=True)
    young_heifers = models.IntegerField(_('Heifers (younger)'), null=True, blank=True)
    old_calves = models.IntegerField(_('Calves (older)'), null=True, blank=True)
    young_calves = models.IntegerField(_('Calves (younger)'), null=True, blank=True)
    beef_cattle = models.IntegerField(_('Beef cattle'), null=True, blank=True)
    # The milk cows' code, and the one for every other class.
    milk_cows_ref_code = models.CharField(_('Milk cows reference code'), max_length=8, blank=True)
    non_milking_ref_code = models.CharField(_('Non-milking cattle reference code'), max_length=8, blank=True)
    labeled_as_dairy = models.BooleanField(_('Labeled as dairy'), default=False)
    # Computed at import from the counts that aren't blank (animal_units()).
    animal_units = models.FloatField(_('Animal units (EPA)'), default=0)

    class Meta:
        unique_together = [('dairy', 'year')]
        indexes = [
            models.Index(fields=['year', 'dairy']),
        ]

    def __str__(self):
        return f'{self.dairy.name} ({self.year})'

    @property
    def other_cattle(self):
        """Every head but the milk cows, over the counts that aren't blank; None when all are."""
        counts = [getattr(self, field) for field in HERD_FIELDS[1:] if getattr(self, field) is not None]
        return sum(counts) if counts else None

    def estimated(self, field):
        """Whether CARB estimated this class's count rather than it being reported."""
        code = self.milk_cows_ref_code if field == 'milk_cows' else self.non_milking_ref_code
        return code != REPORTED_REF_CODE


class DigesterQuerySet(models.QuerySet):
    def operating_in(self, year):
        """
        Operating in `year`: started by then, or its start year is unknown,
        and not shut down by then.
        """
        return self.filter(
            Q(operational_year__isnull=True) | Q(operational_year__lte=year)
        ).filter(Q(shutdown_year__isnull=True) | Q(shutdown_year__gt=year))


class Digester(models.Model):
    """An anaerobic digester at a dairy, per CADD."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Digester'))
    dairy = models.ForeignKey(Dairy, verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='digesters')
    # Blank for a handful of CADD's AgSTAR rows that carry no start year.
    operational_year = models.IntegerField(_('Operational year'), null=True, blank=True)
    shutdown_year = models.IntegerField(_('Shutdown year'), null=True, blank=True)
    # DDRDP, AgSTAR or LCFS.
    source = models.CharField(_('Data source'), max_length=16, blank=True)

    objects = DigesterQuerySet.as_manager()

    def __str__(self):
        return f'{self.dairy.name} digester ({self.operational_year})'

    def operating_in(self, year):
        return (self.operational_year is None or self.operational_year <= year) \
            and (self.shutdown_year is None or self.shutdown_year > year)
