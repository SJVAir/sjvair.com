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
    city = models.CharField(_('City'), max_length=100, blank=True)
    zip = models.CharField(_('ZIP Code'), max_length=10, blank=True)

    point = models.PointField(_('Location'), srid=4326, geography=False, spatial_index=True)

    county = models.ForeignKey('Region',
        verbose_name=_('County'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    district = models.ForeignKey('Region',
        verbose_name=_('School District'),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='schools',
        limit_choices_to={'type': Region.Type.SCHOOL_DISTRICT},
    )

    metadata = models.JSONField(blank=True, default=dict, encoder=JSONEncoder)
    imported_at = models.DateTimeField(_('Imported At'), default=timezone.now)

    class Meta:
        ordering = ['name']
        unique_together = ('source', 'external_id')

    def __str__(self):
        return self.name

    def get_pesticides_url(self):
        """
        Locations don't have their own page: the district page is the closest
        thing, and a location without a district has nowhere to go.
        """
        if self.district_id is None:
            return ''
        return self.district.get_pesticides_url()

    @property
    def short_type(self):
        return self.SHORT_TYPES[self.Type(self.type)]

    @classmethod
    def county_for(cls, point) -> Optional['Region']:
        """The county Region whose boundary contains the point, if any."""
        return (Region.objects
            .filter(type=Region.Type.COUNTY, boundary__geometry__contains=point)
            .first()
        )

    @classmethod
    def district_for(cls, point, cds_code=None) -> Optional['Region']:
        """
        The school district for a location. Public schools carry a 14-digit
        CDS code whose first 7 digits are the district's, which is exact.
        Everything else falls back to the district containing the point,
        where elementary and unified districts overlap: prefer a unified
        district, then the widest grade span.
        """
        districts = Region.objects.filter(type=Region.Type.SCHOOL_DISTRICT)

        if cds_code:
            district = districts.filter(external_id__startswith=str(cds_code)[:7]).first()
            if district is not None:
                return district

        candidates = list(districts.filter(boundary__geometry__contains=point))
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        unified = [d for d in candidates if 'unified' in d.name.lower()]
        if unified:
            candidates = unified

        return max(candidates, key=lambda district: _grade_span(district.metadata))


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
