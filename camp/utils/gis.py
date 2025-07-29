from django.contrib.gis.geos import GEOSGeometry, MultiPolygon as GEOSMultiPolygon
from shapely.geometry import Polygon, MultiPolygon

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

    # if geom.srid != 4326:
    #     geom.srid = 4326  # Assign if missing
    if geom.geom_type == 'Polygon':
        return GEOSMultiPolygon(geom)
    elif geom.geom_type == 'MultiPolygon':
        return geom
    else:
        raise TypeError(f'Unsupported geometry type: {geom.geom_type}')
