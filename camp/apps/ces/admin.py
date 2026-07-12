from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from camp.apps.ces.models import CES4, CES5
from camp.utils.admin import ReadOnlyAdminMixin, admin_change_link


class CESRecordAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['get_tract', 'census_year', 'ci_score', 'ci_score_p', 'dac_sb535', 'dac_category']
    list_filter = ['boundary__version', 'dac_sb535', 'dac_category']
    list_select_related = ['boundary__region']
    search_fields = ['boundary__region__external_id', 'boundary__region__name']
    readonly_fields = ['tract', 'census_year', 'get_region']

    @admin.display(description=_('Tract'), ordering='boundary__region__external_id')
    def get_tract(self, obj):
        return admin_change_link(obj.region, obj.tract)

    @admin.display(description=_('Region'))
    def get_region(self, obj):
        return admin_change_link(obj.region)


@admin.register(CES4)
class CES4Admin(CESRecordAdmin):
    fieldsets = [
        (None, {
            'fields': ['tract', 'census_year', 'get_region', 'population', 'ci_score', 'ci_score_p'],
        }),
        (_('SB535 Disadvantaged Community'), {
            'fields': ['dac_sb535', 'dac_category'],
        }),
        (_('Pollution Burden'), {
            'fields': [
                'pollution', 'pollution_s', 'pollution_p',
                'pol_ozone', 'pol_ozone_p',
                'pol_pm', 'pol_pm_p',
                'pol_diesel', 'pol_diesel_p',
                'pol_pest', 'pol_pest_p',
                'pol_rsei_haz', 'pol_rsei_haz_p',
                'pol_traffic', 'pol_traffic_p',
                'pol_drink', 'pol_drink_p',
                'pol_haz', 'pol_haz_p',
                'pol_lead', 'pol_lead_p',
                'pol_cleanups', 'pol_cleanups_p',
                'pol_gwthreats', 'pol_gwthreats_p',
                'pol_iwb', 'pol_iwb_p',
                'pol_swis', 'pol_swis_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Population Characteristics'), {
            'fields': [
                'popchar', 'popchar_s', 'popchar_p',
                'char_asthma', 'char_asthma_p',
                'char_cvd', 'char_cvd_p',
                'char_lbw', 'char_lbw_p',
                'char_edu', 'char_edu_p',
                'char_ling', 'char_ling_p',
                'char_pov', 'char_pov_p',
                'char_unemp', 'char_unemp_p',
                'char_housingb', 'char_housingb_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Demographics'), {
            'fields': [
                'pop_under_10', 'pop_10_64', 'pop_65_plus',
                'pop_hispanic', 'pop_white', 'pop_black',
                'pop_native', 'pop_aapi', 'pop_other',
            ],
            'classes': ['collapse'],
        }),
    ]


@admin.register(CES5)
class CES5Admin(CESRecordAdmin):
    list_display = CESRecordAdmin.list_display + ['county']
    list_filter = CESRecordAdmin.list_filter + ['county']
    search_fields = CESRecordAdmin.search_fields + ['zipcode']

    fieldsets = [
        (None, {
            'fields': [
                'tract', 'census_year', 'get_region', 'zipcode', 'approx_loc',
                'county', 'region_name', 'population', 'ci_score', 'ci_score_p',
            ],
        }),
        (_('SB535 Disadvantaged Community'), {
            'fields': ['dac_sb535', 'dac_category'],
        }),
        (_('Pollution Burden'), {
            'fields': [
                'pollution', 'pollution_s', 'pollution_p',
                'pol_ozone', 'pol_ozone_p',
                'pol_pm', 'pol_pm_p',
                'pol_diesel', 'pol_diesel_p',
                'pol_pest', 'pol_pest_p',
                'pol_rsei_haz', 'pol_rsei_haz_p',
                'pol_traffic', 'pol_traffic_p',
                'pol_drink', 'pol_drink_p',
                'pol_lead', 'pol_lead_p',
                'pol_cleanups', 'pol_cleanups_p',
                'pol_gwthreats', 'pol_gwthreats_p',
                'pol_haz', 'pol_haz_p',
                'pol_iwb', 'pol_iwb_p',
                'pol_small_ats', 'pol_small_ats_p',
                'pol_swis', 'pol_swis_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Population Characteristics'), {
            'fields': [
                'popchar', 'popchar_s', 'popchar_p',
                'char_asthma', 'char_asthma_p',
                'char_cvd', 'char_cvd_p',
                'char_diabetes', 'char_diabetes_p',
                'char_lbw', 'char_lbw_p',
                'char_edu', 'char_edu_p',
                'char_ling', 'char_ling_p',
                'char_pov', 'char_pov_p',
                'char_unemp', 'char_unemp_p',
                'char_housingb', 'char_housingb_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Demographics'), {
            'fields': [
                'pop_under_10_pct', 'pop_10_64_pct', 'pop_65_plus_pct',
                'pop_hispanic_pct', 'pop_white_pct', 'pop_black_pct',
                'pop_native_pct', 'pop_asian_pct', 'pop_pacisl_pct', 'pop_other_pct',
            ],
            'classes': ['collapse'],
        }),
    ]
