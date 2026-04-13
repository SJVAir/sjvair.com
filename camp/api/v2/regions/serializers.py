import json

from resticus import serializers


class BoundarySerializer(serializers.Serializer):
    fields = (
        ('id', lambda b: b.sqid),
        'version',
        ('geometry', lambda b: json.loads(b.geometry.geojson)),
    )


class RegionSerializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        'name',
        'slug',
        'type',
        ('boundary', lambda r: BoundarySerializer(r.boundary).serialize() if r.boundary else None),
    )
