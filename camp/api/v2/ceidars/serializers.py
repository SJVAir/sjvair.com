from resticus import serializers


class FacilitySerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        'name',
        ('county', lambda f: f.get_county()),
        ('city', lambda f: f.get_city()),
        ('zipcode', lambda f: f.get_zipcode()),
        'sic_code',
        'point',
    )
