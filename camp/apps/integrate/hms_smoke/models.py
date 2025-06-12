from django.contrib.gis.db import models as gis_models
from django.db import models
from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils.models import TimeStampedModel

"""
Defines the database for holding HMS Wildfire smoke data.
This includes:
    the start/end time of the plume: stored as datetime objects
    satellite: the satellite used to observe the smoke
    density: density of smoke plume ("Light", "Medium", or "Heavy")
    geometry: polygonal smoke region in standard GPS coordinates (srid = 4326)
    ID: unique database ID identifier   
"""
class Density(models.TextChoices):
    LIGHT = 'light', 'Light'
    MEDIUM = 'medium', 'Medium'
    HEAVY = 'heavy', 'Heavy'
    

class Smoke(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    
    satellite = models.CharField(max_length=20)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True) 
    density = models.CharField(max_length=10, choices=Density.choices, default=Density.LIGHT)
    geometry = gis_models.GeometryField(srid=4326)
    
    #default save and lower any density inputs for comparison
    
    def save(self, *args, **kwargs):
        if self.density:
            self.density = self.density.lower()
            if self.density not in Density.values:
                self.density = Density.LIGHT
        super().save(*args, **kwargs)