from resticus import serializers


class SmokeSerializer(serializers.Serializer):
    fields = (
        'id',
        'date',
        'satellite',
        'density',
        'start',
        'end',
        'geometry',
    )


class FireSerializer(serializers.Serializer):
    fields = (
        'id',
        'date',
        'satellite',
        'timestamp',
        'frp',
        'ecosystem',
        'method',
        'geometry',
    )
