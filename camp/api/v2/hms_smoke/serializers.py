from resticus import serializers


class SmokeSerializer(serializers.Serializer):
    fields = (
        'id', 
        'satellite',
        'density', 
        'end', 
        'start', 
        'date',
        'geometry',
        'is_final',
    )
    