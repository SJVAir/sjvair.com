from resticus import serializers


EMISSIONS_FIELDS = (
    'year', 'tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
    'total_score', 'hra', 'chindex', 'ahindex',
    'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
    'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
    'methylene_chloride', 'naphthalene', 'perchloroethylene',
)


class EmissionsSerializer(serializers.Serializer):
    fields = EMISSIONS_FIELDS


class FacilitySerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        'name',
        ('county', lambda f: f.get_county()),
        ('city', lambda f: f.get_city()),
        ('zipcode', lambda f: f.get_zipcode()),
        'sic_code',
        'is_minor_source',
        'point',
    )
