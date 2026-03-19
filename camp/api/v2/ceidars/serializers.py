from resticus import serializers


class FacilitySerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        'name',
        'city',
        'sic_code',
        'position',
    )
