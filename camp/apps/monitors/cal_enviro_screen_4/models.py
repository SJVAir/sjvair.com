from django.db import models

from django_smalluuid.models import SmallUUIDField, uuid_default
from django.contrib.gis.db import models as gis_models

class CalEnviro(models.Model):
    OBJECTID = models.IntegerField(primary_key=True)
    timestamp = models.DateTimeField(null=True)
    tract = models.FloatField(max_length=30, null=True)
    ACS2019Tot = models.FloatField(max_length=20, null=True)
    
    CIscore = models.FloatField(max_length=20,null=True)
    CIscoreP = models.FloatField(max_length=20,null=True)
    
    ozone = models.FloatField(max_length=20,null=True)
    ozoneP = models.FloatField(max_length=20,null=True)
    
    pm = models.FloatField(max_length=20,null=True)
    pmP = models.FloatField(max_length=20,null=True)
    
    diesel = models.FloatField(max_length=20,null=True)
    dieselP = models.FloatField(max_length=20,null=True)
    
    pest = models.FloatField(max_length=20,null=True)
    pestP = models.FloatField(max_length=20,null=True)
    
    RSEIhaz = models.FloatField(max_length=20,null=True)
    RSEIhazP = models.FloatField(max_length=20,null=True)
    
    asthma = models.FloatField(max_length=20,null=True)
    asthmaP = models.FloatField(max_length=20,null=True)
    
    geometry = gis_models.GeometryField(srid=4326)
    