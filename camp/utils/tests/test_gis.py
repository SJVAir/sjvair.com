from django.test import TestCase
from django.contrib.gis.geos import GEOSGeometry
from shapely.geometry import Polygon
from camp.utils.gis import to_multipolygon


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
