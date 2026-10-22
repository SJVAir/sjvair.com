import json

from resticus import serializers


def retired_json(obj):
    """
    The public "this record was retired" marker, or None for a current one.
    `replaced_by` names the replacement by its permanent code: {type,
    external_id} for a Region, {source, external_id} for a Location.
    """
    if obj.retired_at is None:
        return None
    replacement = obj.replaced_by
    if replacement is None:
        replaced_by = None
    elif hasattr(replacement, 'source'):
        replaced_by = {'source': replacement.source, 'external_id': replacement.external_id}
    else:
        replaced_by = {'type': replacement.type, 'external_id': replacement.external_id}
    return {'since': obj.retired_at.isoformat(), 'replaced_by': replaced_by}


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
        'external_id',
        ('retired', retired_json),
        ('boundary', lambda r: BoundarySerializer(r.boundary).serialize() if r.boundary else None),
    )


class RegionListSerializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        'name',
        'slug',
        'type',
        'external_id',
        ('retired', retired_json),
        ('boundary', lambda r: BoundaryListSerializer(r.boundary).serialize() if r.boundary else None),
    )
