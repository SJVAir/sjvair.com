import tempfile

from pathlib import Path
from unittest import mock

import fiona
import geopandas as gpd
from django.test import SimpleTestCase, TestCase
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


class CrsComparisonTests(SimpleTestCase):
    def test_is_same_crs_across_representations(self):
        assert geodata.is_same_crs(4326, 'EPSG:4326')
        assert geodata.is_same_crs(fiona.crs.CRS.from_epsg(4326), gis.EPSG_LATLON)
        assert not geodata.is_same_crs('EPSG:3310', gis.EPSG_LATLON)

    def test_to_src_crs_leaves_latlon_sources_alone(self):
        geom = box(-120.0, 36.5, -119.5, 37.0)
        with mock.patch('camp.utils.geodata.gpd.GeoSeries') as geoseries:
            assert geodata._to_src_crs(geom, fiona.crs.CRS.from_epsg(4326)) is geom
            assert geodata._to_src_crs(geom, None) is geom
        geoseries.assert_not_called()

    def test_to_src_crs_reprojects_other_sources(self):
        geom = box(-120.0, 36.5, -119.5, 37.0)
        expected = gpd.GeoSeries([geom], crs=gis.EPSG_LATLON).to_crs(epsg=3310).iloc[0]
        assert geodata._to_src_crs(geom, fiona.crs.CRS.from_epsg(3310)).equals_exact(expected, tolerance=1e-6)


class LoadRegionGeometryTests(TestCase):
    fixtures = ['regions.yaml']

    def test_latlon_crs_in_any_form_is_not_reprojected(self):
        latlon = geodata.load_region_geometry()
        with mock.patch('camp.utils.geodata.gpd.GeoSeries') as geoseries:
            assert geodata.load_region_geometry(fiona.crs.CRS.from_epsg(4326)).equals(latlon)
            assert geodata.load_region_geometry('EPSG:4326').equals(latlon)
        geoseries.assert_not_called()

    def test_other_crs_is_reprojected(self):
        expected = gpd.GeoSeries([geodata.load_region_geometry()], crs=gis.EPSG_LATLON).to_crs(epsg=3310).iloc[0]
        albers = geodata.load_region_geometry(fiona.crs.CRS.from_epsg(3310))
        assert albers.equals_exact(expected, tolerance=1e-6)


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
        self.tmpdir = Path(tmpdir.name)
        self.path = self.write(self.latlon.to_crs(epsg=3310), 'points')

    def write(self, gdf, name):
        path = self.tmpdir / f'{name}.shp'
        gdf.to_file(path)
        return path

    def rows(self, path=None, **kwargs):
        return list(geodata.stream_filtered_gdf(str(path or self.path), **kwargs))

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

    def test_source_already_in_the_requested_crs_is_not_transformed(self):
        path = self.write(self.latlon, 'latlon')
        with mock.patch('camp.utils.geodata.pyproj.Transformer.from_crs') as from_crs:
            rows = self.rows(path)
        from_crs.assert_not_called()
        assert [row.geometry for row in rows] == list(self.latlon.geometry)

    def test_z_is_dropped_with_or_without_reprojection(self):
        points_z = self.latlon.set_geometry([Point(p.x, p.y, 90.0) for p in self.latlon.geometry], crs=gis.EPSG_LATLON)
        for path in (self.write(points_z, 'latlon_z'), self.write(points_z.to_crs(epsg=3310), 'albers_z')):
            rows = self.rows(path)
            assert not any(row.geometry.has_z for row in rows)
            assert rows[0].geometry.equals_exact(Point(-119.7871, 36.7378), tolerance=1e-9)


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
