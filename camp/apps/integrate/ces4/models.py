from django.contrib.gis.db import models as gis_models
from django.db import models

"""
Variable meanings = (-P at the end is the percentile of that variable)
OBJECTID
tract
ACS2019Tot
CIscore
Pollution Burden Variables
    pollution - pollution burden
    pollutionS - pollution burden score
    ozone - Ozone concentrations in air
    pm - PM2.5 concentrations in air
    diesel - Diesel particulate matter emissions 
    pest - Use of certain high-hazard, highvolatility pesticides
    RSEIhaz - Hazardous waste facilities and generators
    traffic - Traffic impacts
    drink - Drinking water contaminants
    lead - Children’s lead risk from housing
    cleanups - Toxic cleanup sites
    gwthreats - Groundwater threats from leaking underground storage sites and cleanups
    iwb - Impaired water bodies
    swis - Solid waste sites and facilities
    
Population Characteristics
    popchar - Population Characteristics
    popcharsco - Population Characteristics Score
    asthma - Asthma emergency department visits
    cvd - Cardiovascular disease (emergency department visits for heart attacks)
    lbw - Low birth-weight infants
    edu - Educational attainment
    ling - Linguistic isolation
    pov - Poverty
    unemp - Unemployment
    housingB - Housing-burdened low-income households

"""
class Ces4(models.Model):
    class Counties(models.TextChoices):
        FRESNO = 'fresno', 'Fresno'
        KERN = 'kern', 'Kern'
        KINGS = 'kings', 'Kings'
        MADERA = 'madera', 'Madera'
        MERCED = 'merced', 'Merced'
        SAN_JOAQUIN = 'san joaquin', 'San Joaquin'
        STANISLAUS = 'stanislaus', 'Stanislaus'
        TULARE = 'tulare', 'Tulare'
        
    OBJECTID = models.IntegerField(primary_key=True)
    tract = models.CharField(max_length=30, null=True)
    ACS2019Tot = models.FloatField(null=True)
    
    CIscore = models.FloatField(null=True)
    CIscoreP = models.FloatField(null=True)
    
    #Pollution Burden Variables
    pollution = models.FloatField(null=True)
    pollutionS = models.FloatField(null=True)
    pollutionP = models.FloatField(null=True)
    
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
    
    traffic = models.FloatField(null=True)
    trafficP = models.FloatField(null=True)
    
    drink = models.FloatField(null=True)
    drinkP = models.FloatField(null=True)
    
    lead = models.FloatField(null=True)
    leadP = models.FloatField(null=True)
    
    cleanups = models.FloatField(null=True)
    cleanupsP = models.FloatField(null=True)
    
    gwthreats = models.FloatField(null=True)
    gwthreatsP = models.FloatField(null=True)
    
    iwb = models.IntegerField(null=True)
    iwbP = models.FloatField(null=True)
    
    swis = models.FloatField(null=True)
    swisP = models.FloatField(null=True)
    
    #Population Characteristics
    popchar = models.FloatField(null=True)
    popcharSco = models.FloatField(null=True)
    popcharP = models.FloatField(null=True)
    
    asthma = models.FloatField(null=True)
    asthmaP = models.FloatField(null=True)
    
    cvd = models.FloatField(null=True)
    cvdP = models.FloatField(null=True)
    
    lbw = models.FloatField(null=True)
    lbwP = models.FloatField(null=True)
    
    edu  = models.FloatField(null=True)
    eduP = models.FloatField(null=True)
    
    ling = models.FloatField(null=True)
    lingP = models.FloatField(null=True)
    
    pov = models.FloatField(null=True)
    povP = models.FloatField(null=True)
    
    unemp = models.FloatField(null=True)
    unempP = models.FloatField(null=True)
    
    housingB = models.FloatField(null=True)
    housingBP = models.FloatField(null=True)
    
    county = models.CharField(
        choices=Counties.choices,
        default=None,
        null=False,
        blank=False,
        ) 
    
    geometry = gis_models.GeometryField(srid=4326)
    