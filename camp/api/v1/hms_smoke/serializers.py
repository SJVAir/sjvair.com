from resticus import serializers
from pytz import timezone



def to_pst(time):
    if time and timezone('UTC'):
            time = time.astimezone(timezone('US/Pacific'))
    return time.strftime("%Y-%m-%d %H:%M:%S %Z%z")

class SmokeSerializer(serializers.Serializer):
    fields = ('id', 'FID', 'satellite','density', ('end', lambda inst: to_pst(inst.end)),
              ('start', lambda inst: to_pst(inst.start)), 
              ('observation_time', lambda inst: to_pst(inst.observation_time))
              , 
              ('geometry')
    )