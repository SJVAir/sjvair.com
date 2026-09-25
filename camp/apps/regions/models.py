from typing import Literal, Optional

from django.contrib.gis.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.regions.managers import RegionManager
from camp.apps.regions.querysets import BoundaryQuerySet
from camp.utils import gis
from camp.utils.encoders import JSONEncoder


class Region(TimeStampedModel):
    class Type(models.TextChoices):
        # Administrative / political boundaries
        COUNTY = 'county', _('County')
        CITY = 'city', _('City')
        ZIPCODE = 'zipcode', _('ZIP Code')

        # Census-based geography
        TRACT = 'tract', _('Census Tract')
        CDP = 'cdp', _('Census Designated Place')

        # Governmental districts
        CONGRESSIONAL_DISTRICT = 'congressional_district', _('Congressional District')
        STATE_ASSEMBLY = 'state_assembly', _('State Assembly District')
        STATE_SENATE = 'state_senate', _('State Senate District')
        SCHOOL_DISTRICT = 'school_district', _('School District')
        AIR_DISTRICT = 'air_district', _('Air District')

        # Environmental / land context
        URBAN_AREA = 'urban_area', _('Urban Area')
        LAND_USE = 'land_use', _('Land Use')
        PROTECTED = 'protected', _('Protected Area')

        # Synthetic community areas (union of UA + city + CDP)
        PLACE = 'place', _('Place')

        # Agricultural survey geography (PLSS / MTRS)
        MTRS = 'mtrs', _('MTRS Section')

        # Catch-all for user-defined regions
        CUSTOM = 'custom', _('Custom Region')

    class Category(models.TextChoices):
        ADMINISTRATIVE = 'administrative', _('Administrative / Political')
        CENSUS = 'census', _('Census-Based Geography')
        DISTRICT = 'district', _('Governmental District')
        ENVIRONMENTAL = 'environmental', _('Environmental / Land Context')
        SYNTHETIC = 'synthetic', _('Synthetic Community Area')
        AGRICULTURAL = 'agricultural', _('Agricultural Survey Geography')
        CUSTOM = 'custom', _('Custom')

    # Maps each Type to the Category it belongs to, mirroring the
    # groupings above. Kept as an explicit mapping (rather than deriving
    # it from Type ordering) so the API's category field doesn't silently
    # shift if Type choices are reordered.
    TYPE_CATEGORIES = {
        Type.COUNTY: Category.ADMINISTRATIVE,
        Type.CITY: Category.ADMINISTRATIVE,
        Type.ZIPCODE: Category.ADMINISTRATIVE,

        Type.TRACT: Category.CENSUS,
        Type.CDP: Category.CENSUS,

        Type.CONGRESSIONAL_DISTRICT: Category.DISTRICT,
        Type.STATE_ASSEMBLY: Category.DISTRICT,
        Type.STATE_SENATE: Category.DISTRICT,
        Type.SCHOOL_DISTRICT: Category.DISTRICT,
        Type.AIR_DISTRICT: Category.DISTRICT,

        Type.URBAN_AREA: Category.ENVIRONMENTAL,
        Type.LAND_USE: Category.ENVIRONMENTAL,
        Type.PROTECTED: Category.ENVIRONMENTAL,

        Type.PLACE: Category.SYNTHETIC,

        Type.MTRS: Category.AGRICULTURAL,

        Type.CUSTOM: Category.CUSTOM,
    }

    # The community layers, each shown as-is (never merged), with the short
    # label the explorers give them: a CDP reads as a "Community". Plain
    # strings, not lazy ones: they end up in cached, JSON-embedded lists.
    COMMUNITY_LABELS = {
        Type.CITY: 'City',
        Type.URBAN_AREA: 'Urban area',
        Type.CDP: 'Community',
    }
    COMMUNITY_TYPES = tuple(COMMUNITY_LABELS)

    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Region'))

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    external_id = models.CharField(max_length=64, blank=True, null=True)
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)

    metadata = models.JSONField(blank=True, default=dict, encoder=JSONEncoder)
    boundary = models.OneToOneField('Boundary', null=True, blank=True, on_delete=models.SET_NULL, related_name='current_for',)

    objects = RegionManager()

    @property
    def short_name(self):
        """The name without a trailing " County": for tables and pickers that already say "county"."""
        if self.type == self.Type.COUNTY and self.name.endswith(' County'):
            return self.name[:-len(' County')]
        return self.name

    @property
    def type_label(self):
        """The type as the explorers show it: a community layer's short label, else the type's own."""
        return self.COMMUNITY_LABELS.get(self.type) or self.get_type_display()

    class Meta:
        indexes = [
            models.Index(fields=['type']),
        ]
        ordering = ['type', 'name']
        unique_together = ('external_id', 'type')

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    def get_pesticides_url(self):
        """This region's page in the pesticides explorer (the app that owns the URL keeps the name)."""
        return reverse('pesticides:region', kwargs={'sqid': self.sqid, 'slug': self.slug})

    @property
    def monitors(self):
        """
        Returns a queryset of all monitors located within this region.

        Filters against the boundary geometry via a correlated subquery rather
        than `self.boundary.geometry`, so the geometry is never deserialized
        into a Python-side GEOS object here — avoids a per-call native memory
        cost that adds up fast when this is called once per region across a
        large batch (e.g. summary backfill, which processes ~1800 regions).
        """
        from camp.apps.monitors.models import Monitor
        if self.boundary_id:
            return Monitor.objects.filter(
                position__intersects=models.Subquery(
                    Boundary.objects.filter(pk=self.boundary_id).values('geometry')[:1]
                ),
            )
        return Monitor.objects.none()


class Boundary(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Boundary'))

    region = models.ForeignKey('Region', related_name='boundaries', on_delete=models.CASCADE)
    version = models.CharField(max_length=32)  # e.g. '2020', '2023-2024', etc
    geometry = models.MultiPolygonField()
    metadata = models.JSONField(blank=True, default=dict, encoder=JSONEncoder)

    objects = BoundaryQuerySet.as_manager()

    class Meta:
        unique_together = ('region', 'version')
        ordering = ['region', '-version']

    def __str__(self):
        return f'{self.region.name} ({self.region.get_type_display()}, v{self.version})'

    @cached_property
    def geom_latlon(self):
        """Geometry in WGS 84 (EPSG:4326) - for display or GPS comparisons"""
        clone = self.geometry.clone()
        clone.transform(gis.EPSG_LATLON)
        return clone

    @cached_property
    def geom_web_mercator(self):
        """Geometry in Web Mercator (EPSG:3857) - for use with tile maps"""
        clone = self.geometry.clone()
        clone.transform(gis.EPSG_WEBMERCATOR)
        return clone

    @cached_property
    def geom_california_albers(self):
        """Geometry in California Albers (EPSG:3310) - for area and length calculations"""
        clone = self.geometry.clone()
        clone.transform(gis.EPSG_CALIFORNIA_ALBERS)
        return clone

    @cached_property
    def orientation(self) -> Literal['landscape', 'portrait']:
        """
        Determines if a geometry is better suited to a landscape or portrait map size.
        (width, height): Size tuple for static map rendering.
        """
        minx, miny, maxx, maxy = self.geometry.extent
        width = maxx - minx
        height = maxy - miny

        if width >= height:
            return 'landscape'
        return 'portrait'

    @property
    def area(self):
        return self.geom_california_albers.area / 2.59e+6

    @property
    def perimeter(self):
        return self.geom_california_albers.length / 1609.34

    @property
    def monitors(self):
        """
        Returns a queryset of all monitors located within this boundary.

        Filters via a correlated subquery instead of self.geometry - see
        Region.monitors above for the same fix and its rationale.
        """
        from camp.apps.monitors.models import Monitor
        return Monitor.objects.filter(
            position__within=models.Subquery(
                Boundary.objects.filter(pk=self.pk).values('geometry')[:1]
            ),
        )


def _point_ewkb(point):
    """
    A comparable snapshot of a point. GEOSGeometry is mutable -- assigning
    `location.point.coords` moves the very object a saved reference points
    at -- so the snapshot has to be its bytes, not the geometry itself.
    """
    return point.ewkb if point is not None else None


class Location(TimeStampedModel):
    """
    A point of interest near which pesticide use matters: schools and child
    care facilities. Points rather than boundaries, so not a Region.
    """

    class Type(models.TextChoices):
        PUBLIC_SCHOOL = 'public_school', _('Public School')
        PRIVATE_SCHOOL = 'private_school', _('Private School')
        CHILD_CARE = 'child_care', _('Child Care')

    SHORT_TYPES = {
        Type.PUBLIC_SCHOOL: _('Public school'),
        Type.PRIVATE_SCHOOL: _('Private school'),
        Type.CHILD_CARE: _('Child care'),
    }

    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Location'))

    type = models.CharField(_('Type'), max_length=32, choices=Type.choices, db_index=True)
    name = models.CharField(_('Name'), max_length=200)
    external_id = models.CharField(_('External ID'), max_length=64)
    source = models.CharField(_('Source'), max_length=32)

    address = models.CharField(_('Address'), max_length=200, blank=True)
    city_name = models.CharField(_('City Name'), max_length=100, blank=True)
    zip = models.CharField(_('ZIP Code'), max_length=10, blank=True)

    point = models.PointField(_('Location'), srid=4326, geography=False, spatial_index=True)

    county = models.ForeignKey('Region',
        verbose_name=_('County'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='county_locations',
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    city = models.ForeignKey('Region',
        verbose_name=_('City'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='city_locations',
        limit_choices_to={'type__in': [Region.Type.CITY, Region.Type.CDP]},
    )
    zipcode = models.ForeignKey('Region',
        verbose_name=_('ZIP Code'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='zipcode_locations',
        limit_choices_to={'type': Region.Type.ZIPCODE},
    )
    school_district = models.ForeignKey('Region',
        verbose_name=_('School District'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='district_locations',
        limit_choices_to={'type': Region.Type.SCHOOL_DISTRICT},
    )

    metadata = models.JSONField(blank=True, default=dict, encoder=JSONEncoder)
    imported_at = models.DateTimeField(_('Imported At'), default=timezone.now)

    # The region links resolve_regions() fills in, in the order it fills them.
    REGION_FIELDS = ('county', 'city', 'zipcode', 'school_district')

    class Meta:
        ordering = ['name']
        unique_together = ('source', 'external_id')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The point the region links were last resolved against, as EWKB:
        # nothing yet for a new instance, the loaded point for a row from
        # the DB. It's a snapshot rather than the Point itself because a
        # Point is mutable -- holding a reference to the live one would
        # compare it against itself and never see a move.
        self._resolved_point = None

    @classmethod
    def from_db(cls, db, field_names, values):
        """
        Snapshot the point as it was loaded: a row's region links are in
        step with its stored point, so save() can tell whether the location
        actually moved and only then pay for re-resolving them.
        """
        instance = super().from_db(db, field_names, values)
        instance._resolved_point = _point_ewkb(instance.__dict__.get('point'))
        return instance

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """
        Keep the region links in step with the point without doing spatial
        work on every write: a new row resolves whatever links it wasn't
        given, and an existing row re-resolves only when its point moved.
        """
        resolved = False
        if self._state.adding:
            # An importer that resolved the links itself has already paid
            # for the spatial queries; don't run them a second time.
            if self._resolved_point is None:
                unset = [field for field in self.REGION_FIELDS
                    if getattr(self, f'{field}_id') is None]
                if unset:
                    self.resolve_regions(fields=unset)
                    resolved = True
        elif self._point_changed():
            self.resolve_regions()
            resolved = True

        if resolved and kwargs.get('update_fields') is not None:
            # A caller saving a named subset of fields ("just the point")
            # doesn't know we re-resolved the links; without adding them the
            # new links live on the instance and never reach the database.
            kwargs['update_fields'] = self._with_region_fields(kwargs['update_fields'])

        super().save(*args, **kwargs)
        self._resolved_point = _point_ewkb(self.__dict__.get('point'))

    def _with_region_fields(self, update_fields):
        names = list(update_fields)
        for field in self.REGION_FIELDS:
            name = f'{field}_id'
            if name not in names:
                names.append(name)
        return names

    def _point_changed(self):
        current = _point_ewkb(self.__dict__.get('point'))
        if current is None:
            # Deferred and never touched: it can't have moved.
            return False
        if self._resolved_point is None:
            return True
        return current != self._resolved_point

    def resolve_regions(self, cds_code=None, fields=None):
        """
        Set the region links from `point` by boundary containment. Returns
        the instance without saving it; `fields` limits which links are
        touched, and `cds_code` is a school's 14-digit CDS code, whose first
        7 digits name its district exactly.
        """
        if self.point is None:
            return self

        fields = fields or self.REGION_FIELDS

        if 'county' in fields:
            self.county = self._containing(type=Region.Type.COUNTY).first()
        if 'city' in fields:
            self.city = self._city_for()
        if 'zipcode' in fields:
            self.zipcode = self._containing(type=Region.Type.ZIPCODE).first()
        if 'school_district' in fields:
            self.school_district = self._school_district_for(cds_code)

        self._resolved_point = _point_ewkb(self.point)
        return self

    def _containing(self, **kwargs):
        """The Regions of some type whose current boundary contains the point."""
        return Region.objects.filter(boundary__geometry__contains=self.point, **kwargs)

    def _city_for(self) -> Optional['Region']:
        """
        The city or CDP containing the point. A CDP is census geography drawn
        around an unincorporated community and can overlap an incorporated
        city's edge, so an actual city wins.
        """
        candidates = list(self._containing(
            type__in=[Region.Type.CITY, Region.Type.CDP]))
        if not candidates:
            return None
        cities = [region for region in candidates if region.type == Region.Type.CITY]
        return (cities or candidates)[0]

    def _school_district_for(self, cds_code=None) -> Optional['Region']:
        """
        The school district for this location. Public schools carry a
        14-digit CDS code whose first 7 digits are the district's, which is
        exact. Everything else falls back to the district containing the
        point, where elementary and unified districts overlap: prefer a
        unified district, then the widest grade span.
        """
        districts = Region.objects.filter(type=Region.Type.SCHOOL_DISTRICT)

        if cds_code:
            district = districts.filter(external_id__startswith=str(cds_code)[:7]).first()
            if district is not None:
                return district

        candidates = list(districts.filter(boundary__geometry__contains=self.point))
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        unified = [d for d in candidates if 'unified' in d.name.lower()]
        if unified:
            candidates = unified

        return max(candidates, key=lambda district: _grade_span(district.metadata))

    def get_county(self):
        return self.county.name if self.county_id else None

    def get_city(self):
        """
        The city as people write it: the source's postal city, else the linked
        city Region. The link is geographic and may be a census-designated
        place inside a larger city's sphere (Old Fig Garden, Sunnyside) that
        nobody would call their school's city; the postal city is the one
        parents and reporters know.
        """
        return self.city_name or (self.city.name if self.city_id else '')

    def get_zipcode(self):
        return self.zipcode.name if self.zipcode_id else self.zip

    def get_school_district(self):
        return self.school_district.name if self.school_district_id else None

    def get_pesticides_url(self):
        """
        Locations don't have their own page: the school district's page is
        the closest thing, and a location without one has nowhere to go.
        """
        if self.school_district_id is None:
            return ''
        return self.school_district.get_pesticides_url()

    @property
    def short_type(self):
        return self.SHORT_TYPES[self.Type(self.type)]


# Grade labels as CDE writes them, lowest first. Anything unrecognized
# sorts as if it were missing.
GRADE_ORDER = ['P', 'PK', 'TK', 'K'] + [str(grade) for grade in range(1, 15)]


def _grade_value(grade, default):
    try:
        return GRADE_ORDER.index(str(grade).strip().upper())
    except (ValueError, AttributeError):
        return default


def _grade_span(metadata):
    """How many grades a district's span covers, for breaking overlap ties."""
    low = _grade_value((metadata or {}).get('grade_low'), 0)
    high = _grade_value((metadata or {}).get('grade_high'), 0)
    return max(high - low, 0)
