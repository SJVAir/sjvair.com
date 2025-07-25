import os
import uuid

from django.db import models
from django.contrib.gis.db import models as gis_models
from django_smalluuid.models import SmallUUIDField, uuid_default



def file_path(instance, filename):
    unique_id = uuid.uuid4().hex[:8]
    return f"observations/{instance.pollutant}/{instance.timestamp:%Y%m%d%H%M%S}_{unique_id}/{filename}"

class TempoGrid(models.Model):
    class Pollutant(models.TextChoices):
        O3TOT = 'o3tot', 'Ozone'
        HCHO = 'hcho', 'Formaldehyde'
        NO2 = 'no2', 'Nitrogen Dioxide'
        
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    
    pollutant = models.CharField(max_length=5, choices=Pollutant.choices,)
    timestamp = models.DateTimeField(null=True)
    
    shp = models.FileField(upload_to=file_path, null=True, blank=True)
    dbf = models.FileField(upload_to=file_path, null=True, blank=True)
    prj = models.FileField(upload_to=file_path, null=True, blank=True)
    cpg = models.FileField(upload_to=file_path, null=True, blank=True)
    shx = models.FileField(upload_to=file_path, null=True, blank=True)
    