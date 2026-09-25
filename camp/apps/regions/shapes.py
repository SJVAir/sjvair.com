"""
Region outlines as GeoJSON features for maps.

Full precision is exact but heavy (the eight counties are ~850 KB, the ZIP
areas ~10 MB). Simplified shapes run a whole region type through
shapely.coverage_simplify together, so neighbours keep one identical shared
border -- simplifying each shape on its own leaves gaps and doubled lines
where they meet. Each type's simplified set is computed once and cached,
zlib-compressed, for a day.
"""
import json
import zlib

import shapely
from shapely import wkb

from django.core.cache import cache

from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_LATLON, round_coords

# Degrees. ~0.0005 is about 50 m at the valley's latitude: invisible at the
# zooms an area map is read at. Counties get a finer line; they're few.
DEFAULT_TOLERANCE = 0.0005
TOLERANCES = {
    Region.Type.COUNTY: 0.0002,
    Region.Type.ZIPCODE: 0.0015,
    Region.Type.TRACT: 0.0014,
}
SHAPES_TTL = 60 * 60 * 24
SHAPES_KEY = 'regions:v1:simplified:{type}'


def _latlon(geometry):
    if geometry.srid and geometry.srid != EPSG_LATLON:
        geometry = geometry.transform(EPSG_LATLON, clone=True)
    return geometry


def _as_multipolygon(geojson):
    if geojson['type'] == 'Polygon':
        return {'type': 'MultiPolygon', 'coordinates': [geojson['coordinates']]}
    return geojson


def region_feature(region, geometry):
    properties = {'id': region.sqid, 'name': region.name, 'slug': region.slug, 'type': region.type}
    return {'type': 'Feature', 'id': region.sqid, 'geometry': geometry, 'properties': properties}


def full_geometry(region):
    geometry = _latlon(region.boundary.geometry)
    return round_coords(_as_multipolygon(json.loads(geometry.geojson)))


def _simplify(regions, tolerance):
    shapes = [wkb.loads(bytes(_latlon(region.boundary.geometry).wkb)) for region in regions]
    try:
        simplified = shapely.coverage_simplify(shapes, tolerance)
    except shapely.errors.GEOSException:
        # Not a clean coverage (overlaps): fall back to shape by shape.
        simplified = [shapely.simplify(shape, tolerance, preserve_topology=True) for shape in shapes]
    return [round_coords(_as_multipolygon(json.loads(shapely.to_geojson(shape)))) for shape in simplified]


def simplified_features(region_type):
    """Every current region of the type with a boundary, simplified together, sorted by name."""
    key = SHAPES_KEY.format(type=region_type)
    packed = cache.get(key)
    if packed is not None:
        return json.loads(zlib.decompress(packed))
    regions = list(
        Region.objects.filter(type=region_type, boundary__isnull=False)
        .current_vintage().select_related('boundary').order_by('name')
    )
    geometries = _simplify(regions, TOLERANCES.get(region_type, DEFAULT_TOLERANCE)) if regions else []
    features = [region_feature(region, geometry) for region, geometry in zip(regions, geometries)]
    try:
        cache.set(key, zlib.compress(json.dumps(features).encode()), SHAPES_TTL)
    except Exception:
        pass  # Too big to cache: computed again next time, never an error.
    return features
