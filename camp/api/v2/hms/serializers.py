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
        ('frp', lambda fire: float(fire.frp) if fire.frp is not None else None),
        'ecosystem',
        'method',
        'geometry',
    )
