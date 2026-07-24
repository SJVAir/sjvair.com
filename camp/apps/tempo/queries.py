from datetime import datetime

from django.contrib.gis.db.models.functions import GeoFunc
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.db import connection
from django.db.models import F, FloatField

from .models import Granule


class STValue(GeoFunc):
    """
    Wraps PostGIS's ST_Value(raster, band, point) -- returns the pixel
    value at `point` for the given band, or SQL NULL if that pixel is
    the raster's nodata value. GeoFunc (not plain Func) auto-wraps the
    bare `point` argument with the correct GeometryField(srid=...),
    matching how Distance('position', form.point, ...) already works
    in camp/api/v2/monitors/endpoints.py -- a plain Func would not do
    this and would raise a FieldError on a bare Point argument.
    """
    function = 'ST_Value'
    output_field = FloatField()
    geom_param_pos = (2,)

    def __init__(self, raster_expr, band, point, **extra):
        super().__init__(raster_expr, band, point, **extra)


def point_series(product: str, point: Point, start: datetime, end: datetime) -> list[dict]:
    """
    One entry per Granule with `product` and `timestamp` in [start, end]
    (inclusive), ordered by timestamp. `value` is the raster pixel value
    at `point` -- None means that pixel is masked/nodata, not that the
    hour is missing (a missing hour has no entry in the list at all).
    """
    return list(
        Granule.objects
        .filter(product=product, timestamp__gte=start, timestamp__lte=end)
        .annotate(value=STValue(F('raster'), 1, point))
        .order_by('timestamp')
        .values('timestamp', 'is_final', 'version', 'value')
    )


def value_at_point(product: str, timestamp: datetime, point: Point) -> float | None:
    """Single-hour convenience wrapper -- snaps `timestamp` to the top of the hour."""
    snapped = timestamp.replace(minute=0, second=0, microsecond=0)
    results = point_series(product, point, snapped, snapped)
    return results[0]['value'] if results else None


def region_series(product: str, polygon: Polygon | MultiPolygon, start: datetime, end: datetime) -> list[dict]:
    """
    One summary-stats entry per Granule with `product` and `timestamp` in
    [start, end] (inclusive), ordered by timestamp. Each row's raster is
    clipped to `polygon` before aggregating, so stats reflect only pixels
    inside the boundary. All-None stat fields (not a missing row) mean the
    polygon produced zero valid pixels for that hour -- distinct from the
    hour being absent from the list entirely.
    """
    sql = f'''
        SELECT
            timestamp,
            is_final,
            version,
            (stats).count,
            (stats).sum,
            (stats).mean,
            (stats).stddev,
            (stats).min,
            (stats).max
        FROM (
            SELECT
                timestamp,
                is_final,
                version,
                ST_SummaryStats(ST_Clip(raster, ST_GeomFromText(%(polygon_wkt)s, 4326))) AS stats
            FROM {Granule._meta.db_table}
            WHERE product = %(product)s
              AND timestamp >= %(start)s
              AND timestamp <= %(end)s
        ) sub
        ORDER BY timestamp
    '''
    params = {
        'polygon_wkt': polygon.wkt,
        'product': product,
        'start': start,
        'end': end,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def zonal_stats(product: str, timestamp: datetime, polygon: Polygon | MultiPolygon) -> dict | None:
    """Single-hour convenience wrapper -- snaps `timestamp` to the top of the hour."""
    snapped = timestamp.replace(minute=0, second=0, microsecond=0)
    results = region_series(product, polygon, snapped, snapped)
    if not results:
        return None
    row = dict(results[0])
    row.pop('timestamp', None)
    row.pop('is_final', None)
    row.pop('version', None)
    return row
