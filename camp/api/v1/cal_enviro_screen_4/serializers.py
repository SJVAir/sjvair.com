from resticus import serializers




class Cal_Enviro_Screen_4_Serializer(serializers.Serializer):
    fields = ('OBJECTID', 'timestamp','tract','ACS2019Tot',
              'CIscore','CIscoreP',
              'ozone','ozoneP',
              'pm','pmP',
              'diesel','dieselP',
              'pest','pestP',
              'RSEIhaz','RSEIhazP',
              'asthma','asthmaP',
            ('geometry')
    )