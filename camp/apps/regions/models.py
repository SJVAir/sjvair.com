from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.regions.querysets import RegionQuerySet


class Region(TimeStampedModel):
    class Type(models.TextChoices):
        CITY = 'city', _('City')
        COUNTY = 'county', _('County')
        ZIPCODE = 'zipcode', _('ZIP Code')
        TRACT = 'tract', _('Census Tract')
        CDP = 'cdp', _('Census Designated Place')
        SCHOOL_DISTRICT = 'school_district', _('School District')
        CONGRESSIONAL_DISTRICT = 'congressional_district', _('Congressional District')
        STATE_ASSEMBLY = 'state_assembly', _('State Assembly District')
        STATE_SENATE = 'state_senate', _('State Senate District')
        CUSTOM = 'custom', _('Custom Region')

    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Region'))

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    external_id = models.CharField(max_length=64, blank=True, null=True)
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)

    boundary = models.OneToOneField('Boundary', null=True, blank=True, on_delete=models.SET_NULL, related_name='current_for',)

    objects = RegionQuerySet.as_manager()

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
            return Monitor.objects.filter(position__within=self.boundary.geometry)
        return Monitor.objects.none()


class Boundary(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Boundary'))

    region = models.ForeignKey('Region', related_name='boundaries', on_delete=models.CASCADE)
    version = models.CharField(max_length=32)  # e.g. '2020', '2023-2024', etc
    geometry = models.MultiPolygonField()
    metadata = models.JSONField(blank=True, default=dict)

    class Meta:
        unique_together = ('region', 'version')

    def __str__(self):
        return f'{self.region.name} ({self.region.get_type_display()}, v{self.version})'

    @property
    def monitors(self):
        """
        Returns a queryset of all monitors located within this region.
        """
        from camp.apps.monitors.models import Monitor
        return Monitor.objects.filter(position__within=self.geometry)
