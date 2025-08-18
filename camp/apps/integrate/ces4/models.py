from django.db import models
from django.utils.translation import gettext_lazy as _


"""
Descriptions quoted from ces4 data dictionary

Labels:
    _p = percentile
    _s = score
    _b = burden
    pol_ = pollution burden class
    char_ = population characteristics class
    pop_ = population demographics class
     
OBJECTID
tract - Census Tract ID from 2010 Census
population - 2019 ACS population estimates in census tracts 
ci_score - CalEnviroScreen Score, Pollution Score multiplied by Population 
    Characteristics Score

Pollution Burden Variables
    pollution -  Average of percentiles from the Pollution Burden indicators (with a half 
        weighting for the Environmental Effects indicators)
    pol_ozone - Amount of daily maximum 8 hour Ozone concentration 
    pol_pm -  Annual mean PM2.5 concentrations
    pol_diesel - Diesel PM emissions from on-road and non-road sources
    pol_pest - Total pounds of selected active pesticide ingredients (filtered for hazard 
        and volatility) used in production-agriculture per square mile 
    pol_rsei_haz -  Toxicity-weighted concentrations of modeled chemical releases to air 
        from facility emissions and off-site incineration (from RSEI)
    pol_traffic -  Traffic density in vehicle-kilometers per hour per road length, within 
        150 meters of the census tract boundary
    pol_drink - Drinking water contaminant index for selected contaminants
    pol_haz - Sum of weighted hazardous waste facilities and large quantity 
        generators within buffered distances to populated blocks of census 
        tracts
    pol_lead -  Potential risk for lead exposure in children living in low-income 
        communities with older housing
    pol_cleanups -  Sum of weighted EnviroStor cleanup sites within buffered distances to 
        populated blocks of census tracts
    pol_gwthreats - Sum of weighted GeoTracker leaking underground storage tank sites  
        within buffered distances to populated blocks of census tracts
    pol_iwb - Sum of number of pollutants across all impaired water bodies within 
        buffered distances to populated blocks of census tracts
    pol_swis - Sum of weighted solid waste sites and facilities (SWIS) within  buffered 
        distances to populated blocks of census tracts
    
Population Characteristics
    popchar - Average of percentiles from the Population Characteristics indicators
    char_asthma - Age-adjusted rate of emergency department visits for asthma
    char_cvd - Age-adjusted rate of emergency department visits for heart attacks per 
        10,000
    char_lbw - Percent low birth weight
    char_edu - Percent of population over 25 with less than a high school education
    char_ling - Percent limited English speaking households
    char_pov - Percent of population living below two times the federal poverty level
    char_unemp - Percent of the population over the age of 16 that is unemployed and 
        eligible for the labor force
    char_housingb - Percent housing-burdened low-income households

 Population Demographics (2019 ACS population estimates)
    pop_10 - percent per census tract of children under 10 years old
    pop_10_64 - percent per census tract of people between 10 and 64 years old
    pop_65 -  percent per census tract of elderly 65 years and older  
    pop_hispanic - percent per census tract of those who identify as Hispanic or Latino
    pop_white - percent per census tract of those who identify as non-Hispanic white
    pop_black - percent per census tract of those who identify as non-Hispanic African American or black 
    pop_native - percent per census tract of those who identify as non-Hispanic Native American
    pop_asian - percent per census tract of those who identify as non-Hispanic Asian or Pacific Islander
    pop_other - percent per census tract of those who identify as non-Hispanic "other" or as multiple races 

"""
class Record(models.Model):
    objectid = models.CharField(_('Tract GEOID + version'), primary_key=True, max_length=20, help_text=_('Given Tract GEOID and census year'))
    tract = models.CharField(_('Tract GEOID'), max_length=12, help_text=_('Given Tract GEOID'))
    population = models.IntegerField(_('Tract Population Size'), null=True, help_text=_('Number of individuals living within the tract'))
    
    # CalEnviroScreen Score, Pollution Score multiplied by Population Characteristics Score
    ci_score = models.FloatField(_('CalEnviroScreen Score'), null=True, help_text=_('Pollution Score multiplied by Population Characteristics Score'))
    ci_score_p = models.FloatField(_('CES Score Percentile'), null=True)
    
    # Pollution Burden Variables
    # Average of percentiles from the Pollution Burden indicators (with a half 
    # weighting for the Environmental Effects indicators)
    pollution = models.FloatField(_('Pollution Burden'), null=True, help_text=_('Average of percentiles from the Pollution Burden indicators'))
    pollution_s = models.FloatField(_('Pollution Burden Score'), null=True)
    pollution_p = models.FloatField(_('Pollution Burden Percentile'), null=True)

    # Amount of daily maximum 8 hour Ozone concentration
    pol_ozone = models.FloatField(_('Ozone (ppm)'), null=True, help_text=_('Amount of daily maximum 8 hour Ozone concentration'))
    pol_ozone_p = models.FloatField(_('Ozone Percentile'), null=True)
    
    # Annual mean PM2.5 concentrations
    pol_pm = models.FloatField(_('PM2.5 (µg/m³)'), null=True, help_text=_('Annual mean PM2.5 concentrations'))
    pol_pm_p = models.FloatField(_('PM2.5 Percentile'), null=True)
    
    # Diesel PM emissions from on-road and non-road sources
    pol_diesel = models.FloatField(_('Diesel PM emissions (tons per year)'), null=True, help_text=_('Diesel PM emissions from on-road and non-road sources'))
    pol_diesel_p = models.FloatField(_('Diesel PM emissions Percentile'), null=True)
    
    # Total pounds of selected active pesticide ingredients
    pol_pest = models.FloatField(_('Pesticides (lb/mi²)'), null=True, help_text=_('Total pounds of selected active pesticide ingredients'))
    pol_pest_p = models.FloatField(_('Pesticides Percentile'), null=True)
    
    # Toxicity-weighted concentrations of modeled chemical releases to air 
    # from facility emissions and off-site incineration
    pol_rsei_haz = models.FloatField(_('Chemical Release Score'), null=True, help_text=_('Toxicity-weighted concentrations of modeled chemical releases to air from facility emissions and off-site incineration'))
    pol_rsei_haz_p = models.FloatField(_('Chemical Releases Percentile'), null=True)
    
    # Traffic density in vehicle-kilometers per hour per road length, within 
    # 150 meters of the census tract boundary
    pol_traffic = models.FloatField(_('Traffic (vehicle-km/hour/km²)'), null=True, help_text=_('Traffic density in vehicle-kilometers per hour per road length, within 150 meters of the census tract boundary'))
    pol_traffic_p = models.FloatField(_('Traffic Percentile'), null=True)
    
    # Drinking water contaminant index for selected contaminants
    pol_drink = models.FloatField(_('Drinking Water Contaminant Score'), null=True, help_text=_('Drinking water contaminant index for selected contaminants'))
    pol_drink_p = models.FloatField(_('Drinking Water Contaminant Percentile'), null=True)
    
    # Sum of weighted hazardous waste facilities and large quantity 
    # generators within buffered distances to populated blocks of census tracts
    pol_haz = models.FloatField(_('Hazardous Waste Facilities'), null=True, help_text=_('Sum of weighted hazardous waste facilities and large quantity generators within buffered distances to populated blocks of census tracts'))
    pol_haz_p = models.FloatField(_('Hazardous Waste Facilities Percentile'), null=True)
    
    # Potential risk for lead exposure in children living in low-income 
    # communities with older housing
    pol_lead = models.FloatField(_('Lead Exposure Score'), null=True, help_text=_('Potential risk for lead exposure in children living in low-income communities with older housing'))
    pol_lead_p = models.FloatField(_('Lead Exposure Percentile'), null=True)
    
    # Sum of weighted EnviroStor cleanup sites within buffered distances to 
    # populated blocks of census tracts
    pol_cleanups = models.FloatField(_('Cleanup Sites'), null=True, help_text=_('Sum of weighted EnviroStor cleanup sites within buffered distances to populated blocks of census tracts'))
    pol_cleanups_p = models.FloatField(_('Asthma Emergencies Percentile'), null=True)
    
    # Sum of weighted GeoTracker leaking underground storage tank sites  
    # within buffered distances to populated blocks of census tracts
    pol_gwthreats = models.FloatField(_('Ground Water Threats'), null=True, help_text=_('Sum of weighted GeoTracker leaking underground storage tank sites within buffered distances to populated blocks of census tracts'))
    pol_gwthreats_p = models.FloatField(_('Ground Water Threats Percentile'), null=True)
    
    # Sum of number of pollutants across all impaired water bodies within 
    # buffered distances to populated blocks of census tracts
    pol_iwb = models.FloatField(_('Impaired Water Bodies'), null=True, help_text=_('Sum of number of pollutants across all impaired water bodies within buffered distances to populated blocks of census tracts'))
    pol_iwb_p = models.FloatField(_('Impaired Water Bodies Percentile'), null=True)
    
    # Sum of weighted and facilities (SWIS) within  buffered 
    # distances to populated blocks of census tracts
    pol_swis = models.FloatField(_('Solid Waste Sites'), null=True, help_text=_('Sum of weighted and facilities (SWIS) within  buffered distances to populated blocks of census tracts'))
    pol_swis_p = models.FloatField(_('Solid Waste Sites Percentile'), null=True)
    
    # Population Characteristics
    # Average of percentiles from the Population Characteristics indicators
    popchar = models.FloatField(_('Population Characteristics'), null=True, help_text=_('Average of percentiles from the Population Characteristics indicators'))
    popchar_s = models.FloatField(_('Population Score'), null=True)
    popchar_p = models.FloatField(_('Population Percentile'), null=True)
    
    # Age-adjusted rate of emergency department visits for asthma
    char_asthma = models.FloatField(_('Asthma Emergencies (per/10,000)'), null=True, help_text=_('Age-adjusted rate of emergency department visits for asthma'))
    char_asthma_p = models.FloatField(_('Asthma Emergencies Percentile'), null=True)
    
    # Age-adjusted rate of emergency department visits for heart attacks per 10,000
    char_cvd = models.FloatField(_('Heart Attack Emergencies (per/10,000)'), null=True, help_text=_('Age-adjusted rate of emergency department visits for heart attacks per 10,000'))
    char_cvd_p = models.FloatField(_('Heart Attack Emergencies Percentile'), null=True)
    
    # Percent low birth weight
    char_lbw = models.FloatField(_('Low Birth Weight'), null=True, help_text=_('Percent of low birth weight'))
    char_lbw_p = models.FloatField(_('Low Birth Weight Percentile'), null=True)
    
    # Percent of population over 25 with less than a high school education
    char_edu  = models.FloatField(_('Education'), null=True, help_text=_('Percent of population over 25 with less than a high school education'))
    char_edu_p = models.FloatField(_('Education Percentile'), null=True)
    
    # Percent limited English speaking households
    char_ling = models.FloatField(_('Linguistic Isolation'), null=True, help_text=_('Percent of households in a census tract where no one over age 14 speaks English'))
    char_ling_p = models.FloatField(_('Linguistic Isolation Percentile'), null=True)
    
    # Percent of population living below two times the federal poverty level
    char_pov = models.FloatField(_('Poverty'), null=True, help_text=_('Percent of population living below two times the federal poverty level'))
    char_pov_p = models.FloatField(_('Poverty Percentile'), null=True)
    
    # Percent of the population over the age of 16 that is unemployed and 
    # eligible for the labor force
    char_unemp = models.FloatField(_('Unemployment'), null=True, help_text=_('Percent of the population over the age of 16 that is unemployed and eligible for the labor force'))
    char_unemp_p = models.FloatField(_('Unemploymentrgencies Percentile'), null=True)
    
    # Percent housing-burdened low-income households
    char_housingb = models.FloatField(_('Low-Income Households'), null=True, help_text=_('Percent housing-burdened low-income households'))
    char_housingb_p = models.FloatField(_('Low-Income Households Percentile'), null=True)
    
    
    # percent per census tract of children under 10 years old
    pop_10 = models.IntegerField(_('Age Group 0-10'), null=True, help_text=_('Number of people per census tract of children under 10 years old'))
    pop_10_p = models.FloatField(_('Age Group 0-10 Percentile'), null=True)
    
    # percent per census tract of people between 10 and 64 years old
    pop_10_64 = models.IntegerField(_('Age Group 10-64'), null=True, help_text=_('Number of people per census tract of people between 10 and 64 years old'))
    pop_10_64_p = models.FloatField(_('Age Group 10-64 Percentile'), null=True)
    
    # percent per census tract of elderly 65 years and older
    pop_65 = models.IntegerField(_('Age Group 65+'), null=True, help_text=_('Number of people per census tract of elderly 65 years and older'))
    pop_65_p = models.FloatField(_('Age Group 65+ Percentile'), null=True)
    
    # percent per census tract of those who identify as Hispanic or Latino
    pop_hispanic = models.IntegerField(_('Hispanic'), null=True, help_text=_('Number of people per census tract of those who identify as Hispanic or Latino'))
    pop_hispanic_p = models.FloatField(_('Hispanic Percentile'), null=True)
    
    # percent per census tract of those who identify as non-Hispanic white
    pop_white = models.IntegerField(_('White'), null=True, help_text=_('Number of people per census tract of those who identify as non-Hispanic white'))
    pop_white_p = models.FloatField(_('White Percentile'), null=True)
    
    # percent per census tract of those who identify as non-Hispanic African American or black
    pop_black = models.IntegerField(_('African American'), null=True, help_text=_('Number of people per census tract of those who identify as non-Hispanic African American or black'))
    pop_black_p = models.FloatField(_('African American Percentile'), null=True)
    
    # percent per census tract of those who identify as non-Hispanic Native American
    pop_native = models.IntegerField(_('Native American'), null=True, help_text=_('Number of people per census tract of those who identify as non-Hispanic Native American'))
    pop_native_p = models.FloatField(_('Native American Percentile'), null=True)
    
    # percent per census tract of those who identify as non-Hispanic Asian or Pacific Islander
    pop_asian = models.IntegerField(_('Asian American'), null=True, help_text=_('Number of people per census tract of those who identify as non-Hispanic Asian or Pacific Islander'))
    pop_asian_p = models.FloatField(_('Asian American Percentile'), null=True)
    
    # percent per census tract of those who identify as non-Hispanic "other" or as multiple races 
    pop_other = models.IntegerField(_('Other Ethnicity'), null=True, help_text=_('Number of people per census tract of those who identify as non-Hispanic "other" or as multiple races'))
    pop_other_p = models.FloatField(_('Other Ethnicity Percentile'), null=True)
    
    boundary = models.OneToOneField('regions.Boundary', null=True, blank=True, on_delete=models.SET_NULL, related_name='record_boundary', help_text=_('Boundary object for this given tract.'))

    @property
    def version(self):
        return self.boundary.version
    