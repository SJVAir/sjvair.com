from django.db import models
from django.contrib.gis.db import models as gis_models
from django_smalluuid.models import SmallUUIDField, uuid_default


class PollutantPoint(models.Model):
    class VerticalColumn(models.TextChoices):
        O3TOT = 'o3tot', 'O3Tot'
        NO2 = 'no2', 'NO2'
        HCHO = 'hcho', 'HCHO'
    
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
     
    timestamp = models.DateTimeField(null=True)
    amount = models.FloatField()
    pollutant = models.CharField(max_length=5, choices=VerticalColumn.choices)
    geometry = gis_models.GeometryField(srid=4326)