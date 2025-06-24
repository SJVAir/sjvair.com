from resticus import serializers


class SmokeSerializer(serializers.Serializer):
    fields = (
        'id', 
        'satellite',
        'density', 
        'end', 
        'start', 
        'timestamp',
        'geometry',
    )
    