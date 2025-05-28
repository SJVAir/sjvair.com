from resticus import serializers
from pytz import timezone



def to_pst(time):
    if time and timezone('UTC'):
            time = time.astimezone(timezone('US/Pacific'))
    return time.strftime("%Y-%m-%d %H:%M:%S %Z%z")

class SmokeSerializer(serializers.Serializer):
    fields = ('id', 'FID', 'satellite', ('end', to_pst),
              ('start', to_pst), 
              ('observation_time', to_pst)
              , 'geometry')