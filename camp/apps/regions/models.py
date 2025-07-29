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
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)
    geometry = models.MultiPolygonField()
    metadata = models.JSONField(blank=True, default=dict)
    external_id = models.CharField(max_length=64, unique=True, blank=True, null=True)

    objects = RegionQuerySet.as_manager()

    class Meta:
        ordering = ['type', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'
