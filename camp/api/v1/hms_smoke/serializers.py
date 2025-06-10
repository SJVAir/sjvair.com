from resticus import serializers
#rm
#from pytz import timezone

#rm
# def to_pst(time):
#     if time and timezone('UTC'):
#             time = time.astimezone(timezone('US/Pacific'))
#     return time.strftime("%Y-%m-%d %H:%M:%S %Z%z")

class SmokeSerializer(serializers.Serializer):
    fields = (
        'id', 
        #rm
        #'FID', 
        'satellite',
        'density', 
        'end', 
        'start', 
        #rm
        # ('end', lambda inst: to_pst(inst.end)),
        # ('start', lambda inst: to_pst(inst.start)), 
        # ('observation_time', lambda inst: to_pst(inst.observation_time)), 
        'created',
        'geometry',
    )