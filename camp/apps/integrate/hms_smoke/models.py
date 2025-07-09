from django.contrib.gis.db import models as gis_models
from django.db import models
from django_smalluuid.models import SmallUUIDField, uuid_default


"""
Defines the database for holding HMS Wildfire smoke data.
This includes:
    the start/end time of the plume: stored as datetime objects
    satellite: the satellite used to observe the smoke
    density: density of smoke plume ("Light", "Medium", or "Heavy")
    geometry: polygonal smoke region in standard GPS coordinates (srid = 4326)
    ID: unique database ID identifier   
"""


class Smoke(models.Model):
    class Density(models.TextChoices):
        LIGHT = 'light', 'Light'
        MEDIUM = 'medium', 'Medium'
        HEAVY = 'heavy', 'Heavy'
    
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    date = models.DateField(null=True)
    satellite = models.CharField(max_length=20)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True) 
    density = models.CharField(max_length=10, choices=Density.choices, default=Density.LIGHT)
    geometry = gis_models.GeometryField(srid=4326)
    is_final = models.BooleanField(default=False)