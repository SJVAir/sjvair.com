import os
import uuid

from django.db import models
from django.contrib.gis.db import models as gis_models
from django_smalluuid.models import SmallUUIDField, uuid_default



def file_path(instance, filename):
    return f"observations/{instance.pollutant}/{instance.timestamp:%Y%m%d%H%M%S}/{filename}"

class TempoGrid(models.Model):
    class Pollutant(models.TextChoices):
        O3TOT = 'o3tot', 'Ozone' #measured in Dobson Units
        HCHO = 'hcho', 'Formaldehyde' #measured in molecules/cm2
        NO2 = 'no2', 'Nitrogen Dioxide' #measured in molecules/cm2
        
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    
    
    pollutant = models.CharField(max_length=5, choices=Pollutant.choices,)
    timestamp = models.DateTimeField(null=True)
    timestamp_2 = models.DateTimeField(null=True, blank=True)
    
    file = models.FileField(upload_to=file_path, null=True, blank=True)
    
    final = models.BooleanField()