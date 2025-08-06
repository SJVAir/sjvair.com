from django.contrib.gis.geos import GEOSGeometry, MultiPolygon as GEOSMultiPolygon
from shapely.geometry import Polygon, MultiPolygon


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
