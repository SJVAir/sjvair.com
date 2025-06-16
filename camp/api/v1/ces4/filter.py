from resticus.filters import FilterSet

from camp.apps.integrate.ces4.models import Ces4

class Ces4Filter(FilterSet):
    class Meta:
        model = Ces4
        fields = {
            'ACS2019Tot': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'CIscore': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'CIscoreP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'ozone': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'ozoneP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pm': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pmP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'diesel': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'dieselP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pest': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pestP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'RSEIhaz': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'RSEIhazP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'asthma': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'asthmaP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'cvd': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'cvdP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pollution': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'pollutionP': [
                'exact',
                'lt', 'lte',
                'gt','gte',
            ],
            'county': [
                'iexact',
                'exact',
            ]
        }