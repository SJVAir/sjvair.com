from resticus.filters import FilterSet

from camp.apps.integrate.ces4.models import Tract


class Ces4Filter(FilterSet):
    class Meta:
        model = Tract
        num_fields = dict.fromkeys(
            [
        'objectid', 'tract', 'population',
        'pollution', 'pollution_p', 'pollution_s',
        'ci_score', 'ci_score_p',
        'ozone', 'ozone_p', 'pm', 'pm_p',
        'diesel', 'diesel_p', 'pest', 'pest_p',
        'rsei_haz', 'rsei_haz_p', 'traffic', 'traffic_p',
        'drink', 'drink_p', 'haz', 'haz_p', 
        'lead', 'lead_p','cleanups', 'cleanups_p',
        'gwthreats', 'gwthreats_p', 'iwb', 'iwb_p',
        'swis', 'swis_p', 'popchar', 'popchar_s', 'popchar_p',
        'asthma', 'asthma_p', 'cvd', 'cvd_p',
        'lbw', 'lbw_p', 'edu', 'edu_p',
        'ling', 'ling_p', 'pov', 'pov_p',
        'unemp', 'unemp_p', 'housingb', 'housing_bp',
        'children_u', 'children_p', 'pop_10_64', 'pop_10_6_p',
        'elderly_65', 'elderly_p', 'hispanic', 'hispanic_p',
        'white', 'white_p', 'african_am', 'african_p',
        'native_am', 'native_am_p', 'asian_am','asian_am_p',
        'other_mult', 'other_mu_p',
             ],
            [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ]
        )
        
        county_field = {
            'county': [
                'iexact', 'exact',
            ]
        }
        
        fields = num_fields | county_field
        