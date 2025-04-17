import json

from resticus import serializers

class CalibratorSerializer(serializers.Serializer):
    fields = [
        'id',
        'reference_id',
        'colocated_id',
        ('name', lambda i: i.reference.name),
        ('position', lambda i: json.loads(i.reference.position.geojson)),
    ]
