from resticus import serializers


class Ces4_Serializer(serializers.Serializer):
    fields = (
        'OBJECTID', 'tract', 'ACS2019Tot',
        'pollution', 'pollutionP', 'pollutionS',
        'CIscore', 'CIscoreP',
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
        'county', 'geometry',
    )
