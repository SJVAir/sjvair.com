from django.contrib.gis.db import models as gis_models
from django.db import models

"""
Descriptions quoted from ces4 data dictionary
OBJECTID
tract - Census Tract ID from 2010 Census
population - 2019 ACS population estimates in census tracts 
ci_score - CalEnviroScreen Score, Pollution Score multiplied by Population 
    Characteristics Score
Pollution Burden Variables
    pollution_b -  Average of percentiles from the Pollution Burden indicators (with a half 
        weighting for the Environmental Effects indicators)
    ozone - Amount of daily maximum 8 hour Ozone concentration 
    pm -  Annual mean PM2.5 concentrations
    diesel - Diesel PM emissions from on-road and non-road sources
    pest - Total pounds of selected active pesticide ingredients (filtered for hazard 
        and volatility) used in production-agriculture per square mile 
    rsei_haz -  Toxicity-weighted concentrations of modeled chemical releases to air 
        from facility emissions and off-site incineration (from RSEI)
    traffic -  Traffic density in vehicle-kilometers per hour per road length, within 
        150 meters of the census tract boundary
    drink - Drinking water contaminant index for selected contaminants
    haz - Sum of weighted hazardous waste facilities and large quantity 
        generators within buffered distances to populated blocks of census 
        tracts
    lead -  Potential risk for lead exposure in children living in low-income 
        communities with older housing
    cleanups -  Sum of weighted EnviroStor cleanup sites within buffered distances to 
        populated blocks of census tracts
    gwthreats - Sum of weighted GeoTracker leaking underground storage tank sites  
        within buffered distances to populated blocks of census tracts
    iwb - Sum of number of pollutants across all impaired water bodies within 
        buffered distances to populated blocks of census tracts
    swis - Sum of weighted solid waste sites and facilities (SWIS) within  buffered 
        distances to populated blocks of census tracts
    
Population Characteristics
    popchar - Average of percentiles from the Population Characteristics indicators
    asthma - Age-adjusted rate of emergency department visits for asthma
    cvd - Age-adjusted rate of emergency department visits for heart attacks per 
        10,000
    lbw - Percent low birth weight
    edu - Percent of population over 25 with less than a high school education
    ling - Percent limited English speaking households
    pov - Percent of population living below two times the federal poverty level
    unemp - Percent of the population over the age of 16 that is unemployed and 
        eligible for the labor force
    housing_b - Percent housing-burdened low-income households

 2019 ACS population estimates:
    children_u - percent per census tract of children under 10 years old
    pop_10_64_ - percent per census tract of people between 10 and 64 years old
    elderly_65 -  percent per census tract of elderly 65 years and older  
    hispanic - percent per census tract of those who identify as Hispanic or Latino
    white - percent per census tract of those who identify as non-Hispanic white
    african_am - percent per census tract of those who identify as non-Hispanic African American or black 
    native_ame - percent per census tract of those who identify as non-Hispanic Native American
    asian_Amer - percent per census tract of those who identify as non-Hispanic Asian or Pacific Islander
    other_mult - percent per census tract of those who identify as non-Hispanic "other" or as multiple races 


"""
class Tract(models.Model):
    class Counties(models.TextChoices):
        FRESNO = 'fresno', 'Fresno'
        KERN = 'kern', 'Kern'
        KINGS = 'kings', 'Kings'
        MADERA = 'madera', 'Madera'
        MERCED = 'merced', 'Merced'
        SAN_JOAQUIN = 'san joaquin', 'San Joaquin'
        STANISLAUS = 'stanislaus', 'Stanislaus'
        TULARE = 'tulare', 'Tulare'
        
    objectid = models.IntegerField(primary_key=True)
    tract = models.CharField(max_length=30, null=True)
    population = models.IntegerField(null=True)
    
    # CalEnviroScreen Score, Pollution Score multiplied by Population Characteristics Score
    ci_score = models.FloatField(null=True)
    ci_score_p = models.FloatField(null=True)
    
    # Pollution Burden Variables
    # Average of percentiles from the Pollution Burden indicators (with a half 
    # weighting for the Environmental Effects indicators)
    pollution = models.FloatField(null=True)
    pollution_s = models.FloatField(null=True)
    pollution_p = models.FloatField(null=True)

    # Amount of daily maximum 8 hour Ozone concentration
    ozone = models.FloatField(null=True)
    ozone_p = models.FloatField(null=True)
    
    # Annual mean PM2.5 concentrations
    pm = models.FloatField(null=True)
    pm_p = models.FloatField(null=True)
    
    # Diesel PM emissions from on-road and non-road sources
    diesel = models.FloatField(null=True)
    diesel_p = models.FloatField(null=True)
    
    # Total pounds of selected active pesticide ingredients
    pest = models.FloatField(null=True)
    pest_p = models.FloatField(null=True)
    
    # Toxicity-weighted concentrations of modeled chemical releases to air 
    # from facility emissions and off-site incineration
    rsei_haz = models.FloatField(null=True)
    rsei_haz_p = models.FloatField(null=True)
    
    # Traffic density in vehicle-kilometers per hour per road length, within 
    # 150 meters of the census tract boundary
    traffic = models.FloatField(null=True)
    traffic_p = models.FloatField(null=True)
    
    # Drinking water contaminant index for selected contaminants
    drink = models.FloatField(null=True)
    drink_p = models.FloatField(null=True)
    
    # Sum of weighted hazardous waste facilities and large quantity 
    # generators within buffered distances to populated blocks of census tracts
    haz = models.IntegerField(null=True)
    haz_p = models.FloatField(null=True)
    
    # Potential risk for lead exposure in children living in low-income 
    # communities with older housing
    lead = models.FloatField(null=True)
    lead_p = models.FloatField(null=True)
    
    # Sum of weighted EnviroStor cleanup sites within buffered distances to 
    # populated blocks of census tracts
    cleanups = models.FloatField(null=True)
    cleanups_p = models.FloatField(null=True)
    
    # Sum of weighted GeoTracker leaking underground storage tank sites  
    # within buffered distances to populated blocks of census tracts
    gwthreats = models.FloatField(null=True)
    gwthreats_p = models.FloatField(null=True)
    
    # Sum of number of pollutants across all impaired water bodies within 
    # buffered distances to populated blocks of census tracts
    iwb = models.IntegerField(null=True)
    iwb_p = models.FloatField(null=True)
    
    # Sum of weighted solid waste sites and facilities (SWIS) within  buffered 
    # distances to populated blocks of census tracts
    swis = models.FloatField(null=True)
    swis_p = models.FloatField(null=True)
    
    # Population Characteristics
    # Average of percentiles from the Population Characteristics indicators
    popchar = models.FloatField(null=True)
    popchar_s = models.FloatField(null=True)
    popchar_p = models.FloatField(null=True)
    
    # Age-adjusted rate of emergency department visits for asthma
    asthma = models.FloatField(null=True)
    asthma_p = models.FloatField(null=True)
    
    # Age-adjusted rate of emergency department visits for heart attacks per 10,000
    cvd = models.FloatField(null=True)
    cvd_p = models.FloatField(null=True)
    
    # Percent low birth weight
    lbw = models.FloatField(null=True)
    lbw_p = models.FloatField(null=True)
    
    #  Percent of population over 25 with less than a high school education
    edu  = models.FloatField(null=True)
    edu_p = models.FloatField(null=True)
    
    # Percent limited English speaking households
    ling = models.FloatField(null=True)
    ling_p = models.FloatField(null=True)
    
    # Percent of population living below two times the federal poverty level
    pov = models.FloatField(null=True)
    pov_p = models.FloatField(null=True)
    
    # Percent of the population over the age of 16 that is unemployed and 
    # eligible for the labor force
    unemp = models.FloatField(null=True)
    unemp_p = models.FloatField(null=True)
    
    # Percent housing-burdened low-income households
    housingb = models.FloatField(null=True)
    housing_bp = models.FloatField(null=True)
    
    # percent per census tract of children under 10 years old
    children_u = models.IntegerField(null=True)
    children_p = models.FloatField(null=True)
    
    # percent per census tract of people between 10 and 64 years old
    pop_10_64 = models.IntegerField(null=True)
    pop_10_6_p = models.FloatField(null=True)
    
    # percent per census tract of elderly 65 years and older
    elderly_65 = models.IntegerField(null=True)
    elderly_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as Hispanic or Latino
    hispanic = models.IntegerField(null=True)
    hispanic_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as non-Hispanic white
    white = models.IntegerField(null=True)
    white_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as non-Hispanic African American or black
    african_am = models.IntegerField(null=True)
    african_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as non-Hispanic Native American
    native_am = models.IntegerField(null=True)
    native_am_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as non-Hispanic Asian or Pacific Islander
    asian_am = models.IntegerField(null=True)
    asian_am_p = models.FloatField(null=True)
    
    # percent per census tract of those who identify as non-Hispanic "other" or as multiple races 
    other_mult = models.IntegerField(null=True)
    other_mu_p = models.FloatField(null=True)
    
    #county this tract is in according to fips number
    county = models.CharField(
        choices=Counties.choices,
        default=None,
        null=False,
        blank=False,
        ) 
    
    #geometric shape of tract
    geometry = gis_models.GeometryField(srid=4326)
    