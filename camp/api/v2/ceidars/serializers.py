from resticus import serializers


class EmissionsSerializer(serializers.Serializer):
    fields = (
        'year', 'tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
        'total_score', 'hra', 'chindex', 'ahindex',
        'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
        'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
        'methylene_chloride', 'naphthalene', 'perchloroethylene',
    )


class FacilitySerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        'facid',
        'name',
        ('address', lambda f: f.address.get('street')),
        ('county_id', lambda f: f.county.sqid if f.county_id else None),
        ('county', lambda f: f.get_county()),
        ('city_id', lambda f: f.city.sqid if f.city_id else None),
        ('city', lambda f: f.get_city()),
        ('zipcode_id', lambda f: f.zipcode.sqid if f.zipcode_id else None),
        ('zipcode', lambda f: f.get_zipcode()),
        'sic_code',
        'is_minor_source',
        'point',
    )
