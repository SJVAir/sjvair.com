from resticus.filters import FilterSet

from camp.apps.integrate.ces4.models import Ces4


class Ces4Filter(FilterSet):
    class Meta:
        model = Ces4
        num_fields = dict.fromkeys(
            [
            'ACS2019Tot', 'CIscore', 'CIscoreP',
            'pollution', 'pollutionP', 'pollutionS',
            'ozone', 'ozoneP', 'pm', 'pmP', 
            'diesel', 'dieselP', 'pest', 'pestP',
            'RSEIhaz', 'RSEIhazP', 'traffic', 'trafficP',
            'drink', 'drinkP', 'lead', 'leadP',
            'cleanups', 'cleanupsP', 'gwthreats', 'gwthreatsP',
            'iwb', 'iwbP', 'swis', 'swisP',
            'popchar', 'popcharSco', 'popcharP',
            'asthma', 'asthmaP', 'cvd', 'cvdP',
            'lbw', 'lbwP', 'edu', 'eduP',
            'ling', 'lingP', 'pov', 'povP',
            'unemp', 'unempP', 'housingB', 'housingBP',
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
        