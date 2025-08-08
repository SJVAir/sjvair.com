from resticus.filters import FilterSet

from camp.apps.integrate.ces4.models import Tract


class Ces4Filter(FilterSet):
    class Meta:
        model = Tract
        fields = dict.fromkeys(
            [
        'tract', 'population',
        'pollution', 'pollution_p', 'pollution_s',
        'ci_score', 'ci_score_p',
        'pol_ozone', 'pol_ozone_p', 'pol_pm', 'pol_pm_p',
        'pol_diesel', 'pol_diesel_p', 'pol_pest', 'pol_pest_p',
        'pol_rsei_haz', 'pol_rsei_haz_p', 'pol_traffic', 'pol_traffic_p',
        'pol_drink', 'pol_drink_p', 'pol_haz', 'pol_haz_p', 
        'pol_lead', 'pol_lead_p', 'pol_cleanups', 'pol_cleanups_p',
        'pol_gwthreats', 'pol_gwthreats_p', 'pol_iwb', 'pol_iwb_p',
        'pol_swis', 'pol_swis_p', 'popchar', 'popchar_s', 'popchar_p',
        'char_asthma', 'char_asthma_p', 'char_cvd', 'char_cvd_p',
        'char_lbw', 'char_lbw_p', 'char_edu', 'char_edu_p',
        'char_ling', 'char_ling_p', 'char_pov', 'char_pov_p',
        'char_unemp', 'char_unemp_p', 'char_housingb', 'char_housingb_p',
        'pop_10', 'pop_10_p', 'pop_10_64', 'pop_10_64_p',
        'pop_65', 'pop_65_p', 'pop_hispanic', 'pop_hispanic_p',
        'pop_white', 'pop_white_p', 'pop_black', 'pop_black_p',
        'pop_native', 'pop_native_p', 'pop_asian','pop_asian_p',
        'pop_other', 'pop_other_p',
             ],
            [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ]
        )
                