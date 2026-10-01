import json

from resticus import serializers


class BoundarySerializer(serializers.Serializer):
    fields = (
        ('id', lambda b: b.sqid),
        'version',
        ('geometry', lambda b: json.loads(b.geometry.geojson)),
        ('bbox', lambda b: list(b.geometry.extent)),
    )


class BoundaryListSerializer(serializers.Serializer):
    """
    Boundary shape for RegionList - omits `geometry`, since converting every
    row's full polygon to GeoJSON dominates list response time (measured
    ~860ms of an ~1.7s response for a 1100-row `within=` narrowing, vs
    ~60ms for `bbox` alone). List consumers only need `bbox` to fit map
    bounds around candidates; full geometry is available per-region via
    RegionDetail once a region is actually selected.
    """
    fields = (
        ('id', lambda b: b.sqid),
        'version',
        ('bbox', lambda b: list(b.geometry.extent)),
    )


class RegionSerializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        'name',
        'slug',
        'type',
        ('boundary', lambda r: BoundarySerializer(r.boundary).serialize() if r.boundary else None),
    )


class RegionListSerializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        'name',
        'slug',
        'type',
        ('boundary', lambda r: BoundaryListSerializer(r.boundary).serialize() if r.boundary else None),
    )
