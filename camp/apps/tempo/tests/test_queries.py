from datetime import datetime, timedelta, timezone as dt_timezone

import numpy as np
from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase

from camp.apps.tempo.models import Granule
from camp.apps.tempo.queries import point_series, region_series, value_at_point, zonal_stats
from camp.apps.tempo.raster import build_raster

# A 3x3 grid covering lon -120..-119, lat 36..37, north-up (row 0 = northernmost, per
# build_raster's documented orientation). Center of each cell is where test points land.
#   col:      -119.833   -119.5     -119.167
# row 36.833:   10         20          30
# row 36.5  :   40         NaN         60
# row 36.167:   70         80          90
GRID = np.array([
    [10.0, 20.0, 30.0],
    [40.0, np.nan, 60.0],
    [70.0, 80.0, 90.0],
])

CENTER_OF_MASKED_CELL = Point(-119.5, 36.5, srid=4326)
CENTER_OF_TOP_LEFT_CELL = Point(-119.833, 36.833, srid=4326)
OUTSIDE_GRID = Point(-100.0, 10.0, srid=4326)

FULL_GRID_POLYGON = Polygon.from_bbox((-120, 36, -119, 37))
FULL_GRID_POLYGON.srid = 4326
OUTSIDE_GRID_POLYGON = Polygon.from_bbox((-100, 10, -99, 11))
OUTSIDE_GRID_POLYGON.srid = 4326


def create_granule(product='no2', timestamp=None, array=GRID, is_final=False, version='V03'):
    timestamp = timestamp or datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
    raster = build_raster(array, lon_min=-120, lat_min=36, lon_max=-119, lat_max=37)
    bounds = Polygon.from_bbox((-120, 36, -119, 37))
    bounds.srid = 4326
    return Granule.objects.create(
        product=product,
        timestamp=timestamp,
        version=version,
        is_final=is_final,
        raster=raster,
        bounds=bounds,
    )


class PointSeriesTests(TestCase):
    def test_returns_value_at_exact_hour(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = point_series('no2', CENTER_OF_TOP_LEFT_CELL, ts, ts)

        assert len(results) == 1
        assert results[0]['timestamp'] == ts
        assert results[0]['value'] == 10.0

    def test_masked_pixel_returns_none_value_with_row_present(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = point_series('no2', CENTER_OF_MASKED_CELL, ts, ts)

        assert len(results) == 1
        assert results[0]['value'] is None

    def test_hour_with_no_granule_is_simply_absent(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = point_series('no2', CENTER_OF_TOP_LEFT_CELL, ts + timedelta(hours=5), ts + timedelta(hours=5))

        assert results == []

    def test_multi_hour_range_returns_entries_ordered_by_timestamp(self):
        ts0 = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        ts1 = ts0 + timedelta(hours=1)
        ts2 = ts0 + timedelta(hours=2)
        create_granule(timestamp=ts1)
        create_granule(timestamp=ts0)
        create_granule(timestamp=ts2)

        results = point_series('no2', CENTER_OF_TOP_LEFT_CELL, ts0, ts2)

        assert [r['timestamp'] for r in results] == [ts0, ts1, ts2]

    def test_point_outside_grid_returns_none_value(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = point_series('no2', OUTSIDE_GRID, ts, ts)

        assert len(results) == 1
        assert results[0]['value'] is None

    def test_wrong_product_is_excluded(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(product='no2', timestamp=ts)

        results = point_series('hcho', CENTER_OF_TOP_LEFT_CELL, ts, ts)

        assert results == []


class ValueAtPointTests(TestCase):
    def test_snaps_off_hour_timestamp_down(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        value = value_at_point('no2', ts + timedelta(minutes=47), CENTER_OF_TOP_LEFT_CELL)

        assert value == 10.0

    def test_returns_none_when_no_granule_for_hour(self):
        value = value_at_point('no2', datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc), CENTER_OF_TOP_LEFT_CELL)

        assert value is None


class RegionSeriesTests(TestCase):
    def test_returns_summary_stats_for_exact_hour(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = region_series('no2', FULL_GRID_POLYGON, ts, ts)

        assert len(results) == 1
        row = results[0]
        assert row['timestamp'] == ts
        # 8 valid pixels (one masked): 10+20+30+40+60+70+80+90 = 400
        assert row['count'] == 8
        assert row['sum'] == 400.0
        assert row['mean'] == 50.0
        assert row['min'] == 10.0
        assert row['max'] == 90.0

    def test_polygon_outside_grid_returns_null_stats_with_row_present(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = region_series('no2', OUTSIDE_GRID_POLYGON, ts, ts)

        assert len(results) == 1
        row = results[0]
        assert row['count'] in (0, None)
        assert row['mean'] is None

    def test_hour_with_no_granule_is_simply_absent(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        results = region_series('no2', FULL_GRID_POLYGON, ts + timedelta(hours=5), ts + timedelta(hours=5))

        assert results == []

    def test_multi_hour_range_returns_entries_ordered_by_timestamp(self):
        ts0 = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        ts1 = ts0 + timedelta(hours=1)
        create_granule(timestamp=ts0)
        create_granule(timestamp=ts1)

        results = region_series('no2', FULL_GRID_POLYGON, ts0, ts1)

        assert [r['timestamp'] for r in results] == [ts0, ts1]


class ZonalStatsTests(TestCase):
    def test_snaps_off_hour_timestamp_down(self):
        ts = datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc)
        create_granule(timestamp=ts)

        stats = zonal_stats('no2', ts + timedelta(minutes=12), FULL_GRID_POLYGON)

        assert stats['count'] == 8
        assert stats['mean'] == 50.0

    def test_returns_none_when_no_granule_for_hour(self):
        stats = zonal_stats('no2', datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc), FULL_GRID_POLYGON)

        assert stats is None
