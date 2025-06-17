from resticus.filters import FilterSet

from camp.apps.integrate.ces4.models import Ces4

class Ces4Filter(FilterSet):
    
    class Meta:
        model = Ces4
        num_fields = dict.fromkeys(
            [
            'ACS2019Tot', 'CIscore', 'CIscoreP',
             'ozone', 'ozoneP',
             'pm', 'pmP', 
             'diesel', 'dieselP',
             'pest', 'pestP',
             'RSEIhaz', 'RSEIhazP',
             'asthma', 'asthmaP',
             'cvd', 'cvdP',
             'pollution', 'pollutionP',
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
        
