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
import logging
import zlib

import shapely
from shapely import wkb

from django.core.cache import cache

from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_LATLON, round_coords

logger = logging.getLogger(__name__)

# Degrees. 0.0005 (~50 m at the valley's latitude) is the spec default,
# invisible at the zooms an area map is read at. Counties get a finer line
# since there are only a handful of them to pay for it; ZIP and tract stay
# at the default -- coarsening them further isn't needed once the compressed
# cache payload (not the raw HTTP body) is what's measured against the
# memcached limit.
DEFAULT_TOLERANCE = 0.0005
TOLERANCES = {Region.Type.COUNTY: 0.0002}
SHAPES_TTL = 60 * 60 * 24
SHAPES_KEY = 'regions:v1:simplified:{type}:{tolerance}'


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


def _simplify(regions, tolerance, region_type):
    shapes = [wkb.loads(bytes(_latlon(region.boundary.geometry).wkb)) for region in regions]
    try:
        # coverage_simplify doesn't raise on overlapping/invalid input -- it
        # silently returns bad topology -- so the coverage is validated
        # first rather than relying on an exception from the simplify call.
        if shapely.coverage_is_valid(shapes):
            simplified = shapely.coverage_simplify(shapes, tolerance)
        else:
            logger.warning(
                'Region type %r is not a valid coverage; simplifying shapes individually.',
                region_type,
            )
            simplified = [shapely.simplify(shape, tolerance, preserve_topology=True) for shape in shapes]
    except (shapely.errors.GEOSException, TypeError):
        # Belt-and-suspenders guard for whatever coverage_is_valid/simplify
        # itself can still raise on: fall back to shape by shape.
        simplified = [shapely.simplify(shape, tolerance, preserve_topology=True) for shape in shapes]
    return [round_coords(_as_multipolygon(json.loads(shapely.to_geojson(shape)))) for shape in simplified]


def simplified_features(region_type):
    """Every current region of the type with a boundary, simplified together, sorted by name."""
    tolerance = TOLERANCES.get(region_type, DEFAULT_TOLERANCE)
    key = SHAPES_KEY.format(type=region_type, tolerance=tolerance)
    packed = cache.get(key)
    if packed is not None:
        return json.loads(zlib.decompress(packed))
    regions = list(
        Region.objects.filter(type=region_type, boundary__isnull=False)
        .current_vintage().select_related('boundary').order_by('name')
    )
    geometries = _simplify(regions, tolerance, region_type) if regions else []
    features = [region_feature(region, geometry) for region, geometry in zip(regions, geometries)]
    try:
        cache.set(key, zlib.compress(json.dumps(features).encode()), SHAPES_TTL)
    except Exception:
        pass  # Too big to cache: computed again next time, never an error.
    return features
