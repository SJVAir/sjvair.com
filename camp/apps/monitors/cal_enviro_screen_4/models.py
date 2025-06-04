from django.db import models

from django_smalluuid.models import SmallUUIDField, uuid_default
from django.contrib.gis.db import models as gis_models

class CalEnviro(models.Model):
    OBJECTID = models.IntegerField(primary_key=True)
    timestamp = models.DateTimeField(null=True)
    tract = models.IntegerField(max_length=30)
    ACS2019Tot = models.IntegerField(max_length=20)
    
    CIscore = models.IntegerField(max_length=20)
    CIscoreP = models.IntegerField(max_length=20)
    
    ozone = models.IntegerField(max_length=20)
    ozoneP = models.IntegerField(max_length=20)
    
    pm = models.IntegerField(max_length=20)
    pmP = models.IntegerField(max_length=20)
    
    diesel = models.IntegerField(max_length=20)
    dieselP = models.IntegerField(max_length=20)
    
    pest = models.IntegerField(max_length=20)
    pestP = models.IntegerField(max_length=20)
    
    RSEIhaz = models.IntegerField(max_length=20)
    RSEIhazP = models.IntegerField(max_length=20)
    
    asthma = models.IntegerField(max_length=20)
    asthmaP = models.IntegerField(max_length=20)
    
    geometry = gis_models.GeometryField(srid=4326)
    