from typing import Literal, Optional

from django.contrib.gis.db import models
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

        # Catch-all for user-defined regions
        CUSTOM = 'custom', _('Custom Region')

    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Region'))

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    external_id = models.CharField(max_length=64, blank=True, null=True)
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)

    boundary = models.OneToOneField('Boundary', null=True, blank=True, on_delete=models.SET_NULL, related_name='current_for',)

    objects = RegionManager()

    class Meta:
        indexes = [
            models.Index(fields=['type']),
        ]
        ordering = ['type', 'name']
        unique_together = ('external_id', 'type')

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    @property
    def monitors(self):
        """
        Returns a queryset of all monitors located within this region.
        """
        from camp.apps.monitors.models import Monitor
        if self.boundary:
            return Monitor.objects.filter(position__intersects=self.boundary.geometry)
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
        Returns a queryset of all monitors located within this region.
        """
        from camp.apps.monitors.models import Monitor
        return Monitor.objects.filter(position__within=self.geometry)
