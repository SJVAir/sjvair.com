from django.db import models
from django.contrib.gis.db import models as gis_models
from django_smalluuid.models import SmallUUIDField, uuid_default


class NO2_Points(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/NO2/', null=True)
    
    
class HCHO_Points(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/HCHO/', null=True)
    
    
class O3TOT_Points(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/O3TOT/', null=True)
    