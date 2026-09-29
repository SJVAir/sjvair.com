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

    # Where the map point came from. Only a Census street match or CARB's own
    # coordinates (pmt.py) are trusted for anything that measures from the
    # point (the schools card): a MapTiler result can be a city centroid, and
    # `legacy` is a point from before this field existed, provenance unknown.
    class PointSource(models.TextChoices):
        CENSUS = 'census', _('Census street match')
        CARB = 'carb', _('CARB coordinates')
        MAPTILER = 'maptiler', _('MapTiler')
        LEGACY = 'legacy', _('Legacy (unknown)')

    TRUSTED_POINT_SOURCES = (PointSource.CENSUS, PointSource.CARB)

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
    point_source = models.CharField(_('Point source'), max_length=16, choices=PointSource.choices, blank=True, default='')

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

    @property
    def has_trusted_point(self):
        """A point we'd measure from: one that exists and came from Census or CARB."""
        return self.point is not None and self.point_source in self.TRUSTED_POINT_SOURCES

    def get_absolute_url(self):
        return reverse('emissions:facility-detail', kwargs={
            'sqid': self.sqid,
            'slug': slugify(self.name) or 'facility',
        })

    def geocode(self):
        """
        Geocodes the facility address, trying Census first then MapTiler, and
        records which one answered in point_source. Sets self.point on success.
        Returns True/False. Does not save.
        """
        street = self.address.get('street', '')
        city = self.address.get('city', '')
        zipcode = self.address.get('zipcode', '')
        query = f'{street}, {city}, CA {zipcode}'
        for source, geocoder in ((self.PointSource.CENSUS, _geocode.census), (self.PointSource.MAPTILER, _geocode.maptiler)):
            point = geocoder(query)
            if point:
                self.point = point
                self.point_source = source
                return True
        return False


class EmissionsRecord(TimeStampedModel):
    """
    One facility's CEIDARS emissions for one inventory year: criteria
    pollutants in tons/yr and the AB 2588 Hot Spots summary fields. Its
    toxic air contaminants are ToxicEmission rows.
    """

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

    # Toxics summary from CARB's AB 2588 Hot Spots program. Set for most SJV
    # facilities (2024: total_score for 4,638, hra for 184, chindex for 158,
    # ahindex for 109); not all facilities have a completed HRA. total_score
    # is the district's Hot Spots prioritization score; hra is the cancer
    # risk per million from the facility's approved health risk assessment;
    # chindex/ahindex are the chronic and acute hazard indices.
    total_score = models.DecimalField(_('Total toxics score'), max_digits=10, decimal_places=2, null=True, blank=True)
    hra = models.DecimalField(_('Health risk assessment'), max_digits=10, decimal_places=2, null=True, blank=True)
    chindex = models.DecimalField(_('Chronic hazard index'), max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(_('Acute hazard index'), max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [('facility', 'year')]
        indexes = [
            models.Index(fields=['year', 'facility']),
        ]

    def __str__(self):
        return f'{self.facility.name} ({self.year})'


class SourceImport(models.Model):
    """
    One finished run of an external-source import (the Consolidated Table,
    the CEIDARS toxics crawl, later ICIS-Air and the rest): when it ran, what
    it covered. Templates read the newest row per source for their "as of"
    stamps; nothing else depends on it.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.SourceImport'))
    source = models.CharField(_('Source'), max_length=32, db_index=True)
    imported_at = models.DateTimeField(_('Imported at'), auto_now_add=True)
    data_through = models.DateField(_('Data through'), null=True, blank=True)
    version = models.CharField(_('Version'), max_length=64, blank=True)
    notes = models.JSONField(_('Notes'), default=dict, blank=True)

    class Meta:
        ordering = ['-imported_at', '-pk']

    def __str__(self):
        return f'{self.source} ({self.imported_at:%Y-%m-%d})'

    @classmethod
    def latest(cls, source):
        return cls.objects.filter(source=source).order_by('-imported_at', '-pk').first()


# CARB's toxicity weighting, reverse-engineered from its Pollution Mapping
# Tool and reproduced to within 0.01% on 91 carcinogens (research:
# .superpowers/research/toxics.md, section 2). Cancer weight per pound is
# the inhalation unit risk × the molecular-weight adjustment factor × 7,700;
# chronic and acute weights are a constant over the reference exposure level.
CANCER_SCALE = 7700.0
CHRONIC_SCALE = 0.01712
ACUTE_SCALE = 0.1712
# Ammonia: CARB delivers it in the toxics feed, but it's a PM2.5 precursor,
# not a toxic; stored under kind='precursor', never weighted or listed as one.
PRECURSOR_IDS = frozenset({'7664417'})
# "PAHs, total, with individual components also reported" -- weighting it
# would count the components twice.
UNWEIGHTED_IDS = frozenset({'1150'})
# The toxics picker's own keys; a pollutant slug can't be one of them.
RESERVED_SLUGS = frozenset({'cancer', 'chronic'})


class ToxicPollutant(models.Model):
    """
    A pollutant in CARB's toxics inventory: a CAS number without dashes
    ('71432', benzene) or one of CARB's own 4-digit codes ('9901', diesel
    PM), with the OEHHA health values from the Consolidated Table and the
    per-pound weights derived from them. Rows exist for every table entry
    and for every id a facility has reported, whether or not both.
    """

    class Kind(models.TextChoices):
        TOXIC = 'toxic', _('Toxic air contaminant')
        PRECURSOR = 'precursor', _('Precursor')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicPollutant'))
    carb_id = models.CharField(_('CARB pollutant ID'), max_length=12, unique=True)
    cas_number = models.CharField(_('CAS number'), max_length=16, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # For URLs (?pollutant=diesel-pm). Set when the row is created, never
    # rewritten, so links stay good when a name is corrected.
    slug = models.SlugField(_('Slug'), max_length=140, unique=True)
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices, default=Kind.TOXIC, db_index=True)
    # OEHHA values as the Consolidated Table gives them.
    iur = models.FloatField(_('Inhalation unit risk (µg/m³)⁻¹'), null=True, blank=True)
    chronic_rel = models.FloatField(_('Chronic REL (µg/m³)'), null=True, blank=True)
    acute_rel = models.FloatField(_('Acute REL (µg/m³)'), null=True, blank=True)
    mwaf = models.FloatField(_('Molecular weight adjustment factor'), default=1.0)
    weighted = models.BooleanField(_('Weighted'), default=True)
    # Derived by set_weights(); 0 where there's no value to derive from.
    cancer_weight = models.FloatField(_('Cancer weight per lb'), default=0.0)
    chronic_weight = models.FloatField(_('Chronic hazard weight per lb'), default=0.0)
    acute_weight = models.FloatField(_('Acute hazard weight per lb'), default=0.0)
    health_values_date = models.DateField(_('Health values date'), null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.carb_id})'

    def set_weights(self):
        """Recompute the three weights from the health values; a precursor or an unweighted id gets none."""
        if self.kind != self.Kind.TOXIC:
            self.cancer_weight = self.chronic_weight = self.acute_weight = 0.0
            return
        self.cancer_weight = self.iur * self.mwaf * CANCER_SCALE if self.weighted and self.iur else 0.0
        self.chronic_weight = CHRONIC_SCALE / self.chronic_rel if self.chronic_rel else 0.0
        self.acute_weight = ACUTE_SCALE / self.acute_rel if self.acute_rel else 0.0

    @staticmethod
    def cas_from_carb_id(carb_id):
        """'71432' -> '71-43-2'; '' for a 4-digit CARB code (a CAS has at least five digits)."""
        carb_id = str(carb_id).strip()
        if len(carb_id) <= 4 or not carb_id.isdigit():
            return ''
        return f'{carb_id[:-3]}-{carb_id[-3:-1]}-{carb_id[-1]}'

    @classmethod
    def unique_slug(cls, name, carb_id):
        """slugify(name), with the CARB id appended when that's taken or reserved."""
        base = slugify(name) or f'pollutant-{carb_id}'
        if base in RESERVED_SLUGS or cls.objects.filter(slug=base).exists():
            # slug's max_length is 140; clip base so 'base-carb_id' still fits.
            clipped = base[:140 - len(carb_id) - 1]
            return f'{clipped}-{carb_id}'
        return base

    @classmethod
    def create_for(cls, carb_id, name):
        """A new row for a CARB id first seen in a facility's CSV: no health values yet."""
        carb_id = str(carb_id).strip()
        return cls.objects.create(
            carb_id=carb_id,
            cas_number=cls.cas_from_carb_id(carb_id),
            name=name,
            slug=cls.unique_slug(name, carb_id),
            kind=cls.Kind.PRECURSOR if carb_id in PRECURSOR_IDS else cls.Kind.TOXIC,
        )


class ToxicEmission(models.Model):
    """One facility's reported pounds of one toxic pollutant in one inventory year (CARB's facdet CSV, EMISSIONS_LBS_YR)."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicEmission'))
    facility = models.ForeignKey(Facility, verbose_name=_('Facility'), on_delete=models.CASCADE, related_name='toxic_emissions')
    year = models.IntegerField(_('Year'))
    pollutant = models.ForeignKey(ToxicPollutant, verbose_name=_('Pollutant'), on_delete=models.PROTECT, related_name='emissions')
    lbs = models.DecimalField(_('Emissions (lbs/yr)'), max_digits=25, decimal_places=15)

    class Meta:
        unique_together = [('facility', 'year', 'pollutant')]
        indexes = [
            models.Index(fields=['year', 'pollutant']),
            models.Index(fields=['pollutant', 'year']),
        ]

    def __str__(self):
        return f'{self.facility.name} {self.pollutant.name} ({self.year})'


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

MATURE_DAIRY_FIELDS = ('milk_cows', 'dry_cows')
OTHER_CATTLE_FIELDS = ('old_heifers', 'young_heifers', 'old_calves', 'young_calves', 'beef_cattle')
HERD_FIELDS = MATURE_DAIRY_FIELDS + OTHER_CATTLE_FIELDS

# EPA's CAFO size thresholds for dairy cattle, in head (40 CFR 122.23(b)(4),(6)):
# a Large CAFO has 700 or more mature dairy cows (milking or dry) or 1,000 or
# more other cattle (heifers, calves, beef); a Medium one 200-699 mature dairy
# cows or 300-999 other cattle. The larger class wins.
LARGE_MATURE_COWS = 700
LARGE_OTHER_CATTLE = 1000
MEDIUM_MATURE_COWS = 200
MEDIUM_OTHER_CATTLE = 300


class SizeClass(models.TextChoices):
    """A dairy's EPA size class in one year (40 CFR 122.23(b)(4),(6))."""
    LARGE = 'large', _('Large')
    MEDIUM = 'medium', _('Medium')
    SMALL = 'small', _('Small')


def size_class(mature_cows, other_cattle):
    """
    The EPA size class of a herd of `mature_cows` and `other_cattle`, the
    larger of the two counts' classes; '' for a herd with no cattle.
    """
    if mature_cows >= LARGE_MATURE_COWS or other_cattle >= LARGE_OTHER_CATTLE:
        return SizeClass.LARGE
    if mature_cows >= MEDIUM_MATURE_COWS or other_cattle >= MEDIUM_OTHER_CATTLE:
        return SizeClass.MEDIUM
    if mature_cows + other_cattle > 0:
        return SizeClass.SMALL
    return ''


def herd_totals(counts):
    """
    {mature_cows, other_cattle, size_class} from {herd field: count}; a blank
    (None) count is unknown and left out of the sums.
    """
    mature = sum(counts.get(field) or 0 for field in MATURE_DAIRY_FIELDS)
    other = sum(counts.get(field) or 0 for field in OTHER_CATTLE_FIELDS)
    return {'mature_cows': mature, 'other_cattle': other, 'size_class': size_class(mature, other)}


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
    # As CADD gives it: street, zipcode. address['city'] is normalized at
    # import: known misspellings/non-city values fixed, then matched against
    # a CITY or CDP Region's name case-insensitively, else title-cased
    # (see camp.apps.emissions.cities).
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
    # Computed at import from the counts that aren't blank (herd_totals()).
    mature_cows = models.PositiveIntegerField(_('Mature dairy cows'), default=0)
    other_cattle = models.PositiveIntegerField(_('Other cattle'), default=0)
    # Blank for a herd with no cattle counted.
    size_class = models.CharField(_('EPA size class'), max_length=8, choices=SizeClass.choices, blank=True)

    class Meta:
        unique_together = [('dairy', 'year')]
        indexes = [
            models.Index(fields=['year', 'dairy']),
        ]

    def __str__(self):
        return f'{self.dairy.name} ({self.year})'

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


class AirComplianceFacility(models.Model):
    """
    A Clean Air Act source in EPA's ICIS-Air, as its bulk files describe it.
    `facility` is the CEIDARS facility it was matched to (see icis.parse_pgm_sys_id);
    unmatched rows are kept but never shown.
    """

    class MatchMethod(models.TextChoices):
        PARSED = 'parsed', _('Parsed from the ICIS id')
        MANUAL = 'manual', _('Hand-kept crosswalk')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.AirComplianceFacility'))
    facility = models.ForeignKey(
        Facility, verbose_name=_('Facility'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='icis_facilities',
    )
    pgm_sys_id = models.CharField(_('ICIS-Air id'), max_length=20, unique=True)
    registry_id = models.CharField(_('FRS registry id'), max_length=12, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # street, city, county, zip as ICIS gives them.
    address = models.JSONField(_('Address'), default=dict, blank=True)
    pollutant_class = models.CharField(_('Pollutant class'), max_length=32, blank=True)
    operating_status = models.CharField(_('Operating status'), max_length=40, blank=True)
    title_v = models.BooleanField(_('Title V'), default=False)
    current_hpv = models.CharField(_('Current HPV status'), max_length=40, blank=True)
    local_region = models.CharField(_('Local control region'), max_length=8, blank=True)
    match_method = models.CharField(_('Match method'), max_length=8, choices=MatchMethod.choices, blank=True)
    # The newest event date for this facility; the card's five-year window ends here.
    reported_through = models.DateField(_('Reported through'), null=True, blank=True)

    class Meta:
        verbose_name_plural = 'air compliance facilities'

    def __str__(self):
        return f'{self.name} ({self.pgm_sys_id})'

    @property
    def hpv_status(self):
        """'unaddressed', 'addressed' or 'none', from ICIS's CURRENT_HPV text ("Unaddressed-Local", "No Violation Identified")."""
        status = self.current_hpv.lower()
        if status.startswith('unaddressed'):
            return 'unaddressed'
        if status.startswith('addressed'):
            return 'addressed'
        return 'none'

    @property
    def dfr_url(self):
        return f'https://echo.epa.gov/detailed-facility-report?fid={self.registry_id}'


class ComplianceEvent(models.Model):
    """One ICIS-Air event: an inspection, a notice of violation, a formal action or an HPV determination."""

    class Kind(models.TextChoices):
        INSPECTION = 'inspection', _('Inspection')
        NOV = 'nov', _('Notice of violation')
        FORMAL = 'formal', _('Formal action')
        HPV = 'hpv', _('High-priority violation')

    class Agency(models.TextChoices):
        LOCAL = 'L', _('Air district')
        STATE = 'S', _('State')
        EPA = 'E', _('EPA')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ComplianceEvent'))
    icis_facility = models.ForeignKey(AirComplianceFacility, verbose_name=_('ICIS facility'), on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices)
    date = models.DateField(_('Date'))
    agency = models.CharField(_('Agency'), max_length=1, choices=Agency.choices, blank=True)
    action_type = models.CharField(_('Action type'), max_length=80, blank=True)
    description = models.TextField(_('Description'), blank=True)
    penalty = models.DecimalField(_('Penalty'), max_digits=12, decimal_places=2, null=True, blank=True)
    program = models.CharField(_('Program'), max_length=40, blank=True)
    pollutant = models.CharField(_('Pollutant'), max_length=40, blank=True)
    # HPV only: the day the violation was resolved.
    resolved = models.DateField(_('Resolved'), null=True, blank=True)
    external_id = models.CharField(_('ICIS activity id'), max_length=40)

    class Meta:
        unique_together = [('icis_facility', 'kind', 'external_id')]
        indexes = [models.Index(fields=['icis_facility', 'kind', 'date'])]

    def __str__(self):
        return f'{self.get_kind_display()} {self.date} ({self.icis_facility.pgm_sys_id})'
