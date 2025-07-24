from django.db import models
from django.contrib.gis.db import models as gis_models
from django_smalluuid.models import SmallUUIDField, uuid_default


class No2File(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/no2/', null=True)
    
    
class HchoFile(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/hcho/', null=True)
    
    
class O3totFile(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(null=True)
    file = models.FileField(upload_to='observations/o3tot/', null=True)
    