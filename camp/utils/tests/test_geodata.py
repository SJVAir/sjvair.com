import tempfile

from pathlib import Path
from unittest import mock

import geopandas as gpd
from django.test import SimpleTestCase
from shapely.geometry import Point, box

from camp.utils import geodata, gis


class FilterByOverlapTests(SimpleTestCase):
    def setUp(self):
        self.region = box(0, 0, 10, 10)
        # A large polygon that only barely overlaps the region (1% of its own area).
        self.plume = box(9, 9, 19, 19)

    def rows(self):
        return iter(gpd.GeoDataFrame({'name': ['plume']}, geometry=[self.plume]).iloc[[0]].pipe(lambda g: [g.iloc[0]]))

    def test_default_threshold_drops_mostly_outside_polygon(self):
        result = list(geodata.filter_by_overlap(self.rows(), self.region))
        assert result == []

    def test_zero_threshold_keeps_any_intersecting_polygon(self):
        result = list(geodata.filter_by_overlap(self.rows(), self.region, threshold=0.0))
        assert len(result) == 1

    def test_zero_threshold_still_drops_non_intersecting_polygon(self):
        self.plume = box(20, 20, 30, 30)
        result = list(geodata.filter_by_overlap(self.rows(), self.region, threshold=0.0))
        assert result == []


class StreamFilteredGdfTests(SimpleTestCase):
    def setUp(self):
        # Fresno and Bakersfield, stored in California Albers (EPSG:3310) so
        # every row has to be reprojected back to lat/lon.
        self.latlon = gpd.GeoDataFrame(
            {'name': ['fresno', 'bakersfield'], 'count': [3, 7]},
            geometry=[Point(-119.7871, 36.7378), Point(-119.0187, 35.3733)],
            crs=gis.EPSG_LATLON,
        )
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.path = Path(tmpdir.name) / 'points.shp'
        self.latlon.to_crs(epsg=3310).to_file(self.path)

    def rows(self, **kwargs):
        return list(geodata.stream_filtered_gdf(str(self.path), **kwargs))

    def test_rows_are_reprojected_to_the_requested_crs(self):
        expected = self.latlon.to_crs(epsg=3310).to_crs(gis.EPSG_LATLON)
        rows = self.rows()
        assert [row.geometry for row in rows] == list(expected.geometry)

    def test_rows_carry_properties_and_geometry(self):
        row = self.rows()[0]
        assert list(row.index) == ['name', 'count', 'geometry']
        assert row['name'] == 'fresno'
        assert row['count'] == 3
        assert row.name == 0

    def test_string_fields_stringifies_the_named_fields(self):
        row = self.rows(string_fields=['count'])[0]
        assert row['count'] == '3'
        assert row['name'] == 'fresno'

    def test_region_geometry_filters_by_bbox(self):
        around_fresno = box(-120.0, 36.5, -119.5, 37.0)
        assert [row['name'] for row in self.rows(region_geometry=around_fresno)] == ['fresno']


class IterFromUrlCacheTests(SimpleTestCase):
    url = 'https://example.com/data.zip'

    def cache_path(self):
        return geodata.GEODATA_CACHE_DIR / f'{geodata.cache_key(self.url)}.zip'

    def setUp(self):
        self.cache_path().write_bytes(b'stale')
        self.addCleanup(lambda: self.cache_path().unlink(missing_ok=True))

    @mock.patch('camp.utils.geodata.iter_from_zip', return_value=iter([]))
    @mock.patch('camp.utils.geodata.stream_to_disk')
    def test_cached_file_is_reused_by_default(self, stream_to_disk, iter_from_zip):
        geodata.iter_from_url(self.url)
        stream_to_disk.assert_not_called()
        iter_from_zip.assert_called_once()

    @mock.patch('camp.utils.geodata.iter_from_zip', return_value=iter([]))
    @mock.patch('camp.utils.geodata.stream_to_disk')
    def test_cache_false_redownloads_over_existing_file(self, stream_to_disk, iter_from_zip):
        geodata.iter_from_url(self.url, cache=False)
        stream_to_disk.assert_called_once()
        assert stream_to_disk.call_args.kwargs['dest'] == self.cache_path()
        iter_from_zip.assert_called_once()
