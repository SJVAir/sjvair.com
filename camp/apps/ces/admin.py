from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from camp.apps.ces.models import CES4


class CESRecordAdmin(admin.ModelAdmin):
    list_display = ['tract', 'census_year', 'ci_score', 'ci_score_p', 'dac_sb535', 'dac_category']
    list_filter = ['boundary__version', 'dac_sb535', 'dac_category']
    search_fields = ['boundary__region__external_id', 'boundary__region__name']
    readonly_fields = ['tract', 'census_year', 'region']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass


@admin.register(CES4)
class CES4Admin(CESRecordAdmin):
    fieldsets = [
        (None, {
            'fields': ['tract', 'census_year', 'region', 'population', 'ci_score', 'ci_score_p'],
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
