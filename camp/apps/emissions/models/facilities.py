from django.contrib.gis.db import models
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
        'emissions.Facility',
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
