from django.contrib.gis.db import models as gis_models
from django.db import models
from model_utils.models import TimeStampedModel


class Counties(models.TextChoices):
    FRESNO = 'fresno', 'Fresno'
    KERN = 'kern', 'Kern'
    KINGS = 'kings', 'Kings'
    MADERA = 'madera', 'Madera'
    MERCED = 'merced', 'Merced'
    SAN_JOAQUIN = 'san joaquin', 'San Joaquin'
    STANISLAUS = 'stanislaus', 'Stanislaus'
    TULARE = 'tulare', 'Tulare'
    

class Ces4(TimeStampedModel):
    OBJECTID = models.IntegerField(primary_key=True)
    tract = models.CharField(max_length=30, null=True)
    ACS2019Tot = models.FloatField(null=True)
    
    CIscore = models.FloatField(null=True)
    CIscoreP = models.FloatField(null=True)
    
    ozone = models.FloatField(null=True)
    ozoneP = models.FloatField(null=True)
    
    pm = models.FloatField(null=True)
    pmP = models.FloatField(null=True)
    
    diesel = models.FloatField(null=True)
    dieselP = models.FloatField(null=True)
    
    pest = models.FloatField(null=True)
    pestP = models.FloatField(null=True)
    
    RSEIhaz = models.FloatField(null=True)
    RSEIhazP = models.FloatField(null=True)
    
    asthma = models.FloatField(null=True)
    asthmaP = models.FloatField(null=True)
    
    cvd = models.FloatField(null=True)
    cvdP = models.FloatField(null=True)
    
    pollution = models.FloatField(null=True)
    pollutionP = models.FloatField(null=True)
    
    county = models.CharField(
        choices=Counties.choices,
        default=None,
        null=False,
        blank=False,
        ) 
    
    geometry = gis_models.GeometryField(srid=4326)
    