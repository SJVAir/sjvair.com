from resticus import serializers


class Ces4_Serializer(serializers.Serializer):
    fields = ('OBJECTID', 'tract','ACS2019Tot',
              'CIscore','CIscoreP',
              'ozone','ozoneP',
              'pm','pmP',
              'diesel','dieselP',
              'pest','pestP',
              'RSEIhaz','RSEIhazP',
              'asthma','asthmaP',
              'cvd', 'cvdP',
              'pollution', 'pollutionP',
              'county', 'created',
              'geometry',
    )
