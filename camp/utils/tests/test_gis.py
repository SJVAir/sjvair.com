from django.test import TestCase
from django.contrib.gis.geos import GEOSGeometry
from shapely.geometry import Polygon
from camp.utils.gis import close_gaps, to_multipolygon


class ToMultipolygonTests(TestCase):
    def test_shapely_polygon(self):
        polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
        result = to_multipolygon(polygon)
        assert result.geom_type == 'MultiPolygon'

    def test_geos_polygon(self):
        geos = GEOSGeometry('POLYGON((0 0, 1 0, 1 1, 0 0))')
        result = to_multipolygon(geos)
        assert result.geom_type == 'MultiPolygon'

    def test_geojson_dict(self):
        geojson = {
            'type': 'Polygon',
            'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]
        }
        result = to_multipolygon(geojson)
        assert result.geom_type == 'MultiPolygon'

    def test_unsupported_type(self):
        with self.assertRaises(TypeError):
            to_multipolygon('not a geometry')

    def test_unsupported_geom_type(self):
        point = GEOSGeometry('POINT(0 0)')
        with self.assertRaises(TypeError):
            to_multipolygon(point)


class CloseGapsTests(TestCase):
    def square(self, x0, size=0.001):
        return f'(({x0} 0, {x0 + size} 0, {x0 + size} {size}, {x0} {size}, {x0} 0))'

    def test_parts_a_hairline_apart_become_one(self):
        # 0.001-degree squares 0.000001 apart (about 10 cm).
        geometry = GEOSGeometry(f'SRID=4326;MULTIPOLYGON({self.square(0)}, {self.square(0.001001)})')
        closed = close_gaps(geometry)
        assert closed.geom_type == 'MultiPolygon'
        assert len(closed) == 1
        assert closed.srid == 4326
        assert abs(closed.area - geometry.area) / geometry.area < 0.01

    def test_parts_far_apart_are_left_alone(self):
        geometry = GEOSGeometry(f'SRID=4326;MULTIPOLYGON({self.square(0)}, {self.square(0.01)})')
        assert close_gaps(geometry) is geometry

    def test_a_single_polygon_is_left_alone(self):
        geometry = GEOSGeometry(f'SRID=4326;MULTIPOLYGON({self.square(0)})')
        assert close_gaps(geometry) is geometry

    def test_corners_stay_corners(self):
        geometry = GEOSGeometry(f'SRID=4326;MULTIPOLYGON({self.square(0)}, {self.square(0.001001)})')
        closed = close_gaps(geometry)
        xmin, ymin, xmax, ymax = closed.extent
        assert (round(xmin, 6), round(ymin, 6), round(xmax, 6), round(ymax, 6)) == (0, 0, 0.002001, 0.001)
