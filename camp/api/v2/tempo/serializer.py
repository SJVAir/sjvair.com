from resticus import serializers


class TempoSerializer(serializers.Serializer):
    fields = {
        'id',
        'pollutant',
        'timestamp',
        'timestamp_2', 
        'file',
        'final',
    }
    