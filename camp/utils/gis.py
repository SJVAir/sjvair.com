from django.contrib.gis.geos import GEOSGeometry, MultiPolygon as GEOSMultiPolygon, Polygon as GEOSPolygon
from shapely.geometry import Polygon, MultiPolygon

# Common EPSG codes
EPSG_LATLON = 4326
EPSG_WEBMERCATOR = 3857
EPSG_CALIFORNIA_ALBERS = 3310


def make_valid(geometry: GEOSGeometry) -> GEOSGeometry:
    """
    Returns a valid version of the given geometry.
    Reconstructs from WKT to strip Z/M values and internal state,
    then applies make_valid() if needed.
    """
    geom = GEOSGeometry(geometry.wkt)  # Strip Z/M if present
    return geom if geom.valid else geom.make_valid()


def to_multipolygon(geom, srid=4326):
    """
    Normalize a geometry input into a GEOS MultiPolygon in EPSG:4326.

    Accepts:
    - Shapely Polygon or MultiPolygon
    - GEOS Polygon or MultiPolygon
    - GeoJSON-like dicts
    """
    if isinstance(geom, dict):
        geom = GEOSGeometry(str(geom), srid=srid)  # accepts GeoJSON-style dicts
    elif isinstance(geom, (Polygon, MultiPolygon)):
        geom = GEOSGeometry(geom.wkt, srid=srid)
    elif not isinstance(geom, GEOSGeometry):
        raise TypeError(f'Unsupported geometry type: {type(geom)}')

    if geom.geom_type == 'Polygon':
        return make_valid(GEOSMultiPolygon(geom))
    elif geom.geom_type == 'MultiPolygon':
        return make_valid(geom)
    else:
        raise TypeError(f'Unsupported geometry type: {geom.geom_type}')


def fill_holes(geometry: GEOSGeometry) -> GEOSMultiPolygon:
    """
    The geometry with every interior ring removed: a city's county islands
    become part of the city. Accepts a GEOS Polygon or MultiPolygon and
    returns a MultiPolygon with the same SRID.
    """
    polygons = [geometry] if geometry.geom_type == 'Polygon' else list(geometry)
    filled = GEOSMultiPolygon([GEOSPolygon(polygon.exterior_ring.clone()) for polygon in polygons])
    filled.srid = geometry.srid
    return filled


# About a metre in degrees at the Valley's latitude.
GAP_TOLERANCE = 1e-5


def close_gaps(geometry: GEOSGeometry, tolerance=GAP_TOLERANCE) -> GEOSGeometry:
    """
    A MultiPolygon whose parts sit a hairline apart (a source's digitizing
    seam: Caltrans' Tulare urban area has an 8.8-acre piece 10 cm off the
    rest) with those gaps closed, so the parts become one shape and an
    outline doesn't trace each part's edge side by side. Grown and shrunk
    back by `tolerance` with mitred joins, so corners stay corners. A
    geometry with no parts that close comes back as it was.
    """
    if geometry.geom_type != 'MultiPolygon' or len(geometry) < 2:
        return geometry
    parts = list(geometry)
    near = any(
        parts[i].distance(parts[j]) < tolerance
        for i in range(len(parts)) for j in range(i + 1, len(parts))
    )
    if not near:
        return geometry
    mitre = 2
    closed = to_multipolygon(geometry.buffer_with_style(tolerance, join_style=mitre).buffer_with_style(-tolerance, join_style=mitre))
    # to_multipolygon rebuilds from WKT, which drops the SRID.
    closed.srid = geometry.srid
    return closed


def has_holes(geometry: GEOSGeometry) -> bool:
    polygons = [geometry] if geometry.geom_type == 'Polygon' else list(geometry)
    return any(polygon.num_interior_rings for polygon in polygons)


def _round(value, precision):
    if isinstance(value, (int, float)):
        return round(value, precision)
    return [_round(item, precision) for item in value]


def round_coords(geometry, precision=5):
    """
    Round a GeoJSON geometry dict's coordinates in place (and return it).
    Five places is about a meter: plenty for a map outline, and it keeps
    payloads a fraction of full precision.
    """
    if geometry and geometry.get('coordinates') is not None:
        geometry['coordinates'] = _round(geometry['coordinates'], precision)
    return geometry
