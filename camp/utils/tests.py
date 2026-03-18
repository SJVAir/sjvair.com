import pytest
import geopandas as gpd
from django.test import TestCase
from shapely.geometry import Point, Polygon

from camp.utils.maps import (
    Area, Marker, StaticMap, from_geometries,
    to_shape, to_geos,
    CRS_WEBMERCATOR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_map(**kwargs):
    """Small StaticMap with no basemap for fast, network-free tests."""
    return StaticMap(width=200, height=150, dpi=72, basemap=None, **kwargs)


# A C-shaped polygon whose bounding-box center (1.5, 1.5) falls in the gap,
# outside the polygon. Used to verify representative_point() behaviour.
C_SHAPE = Polygon([
    (0, 0), (0, 3), (3, 3), (3, 2),
    (1, 2), (1, 1), (3, 1), (3, 0),
])

SQUARE = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])

CA_POLY = Polygon([(-119, 35), (-118, 35), (-118, 36), (-119, 36)])
CA_POINT = Point(-119, 35)


# ---------------------------------------------------------------------------
# to_shape / to_geos
# ---------------------------------------------------------------------------

class ToShapeTests(TestCase):
    def test_shapely_point_converts_to_web_mercator(self):
        result = to_shape(Point(0, 0))
        assert result.geom_type == 'Point'
        assert abs(result.x) < 1
        assert abs(result.y) < 1

    def test_shapely_polygon_converts(self):
        result = to_shape(CA_POLY)
        assert result.geom_type == 'Polygon'

    def test_geos_geometry_converts(self):
        from django.contrib.gis.geos import GEOSGeometry
        result = to_shape(GEOSGeometry('POINT (0 0)', srid=4326))
        assert result.geom_type == 'Point'
        assert abs(result.x) < 1
        assert abs(result.y) < 1


class ToGeosTests(TestCase):
    def test_shapely_to_geos(self):
        from django.contrib.gis.geos import GEOSGeometry
        result = to_geos(Point(0, 0))
        assert isinstance(result, GEOSGeometry)

    def test_geos_passthrough(self):
        from django.contrib.gis.geos import GEOSGeometry
        geos = GEOSGeometry('POINT (0 0)', srid=4326)
        assert to_geos(geos) is geos

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            to_geos('not a geometry')


# ---------------------------------------------------------------------------
# Area.get_label_position
# ---------------------------------------------------------------------------

class AreaLabelPositionTests(TestCase):
    def _pos(self, position, geom=SQUARE):
        return Area(geometry=geom, label_position=position).get_label_position()

    def test_center_is_inside_polygon(self):
        # C-shape: bounding-box midpoint (1.5, 1.5) is in the gap (outside).
        # representative_point() must land inside.
        ha, va, x, y = self._pos('center', C_SHAPE)
        assert C_SHAPE.contains(Point(x, y))

    def test_top_left(self):
        ha, va, x, y = self._pos('top-left')
        assert (ha, va) == ('left', 'top')
        assert x == 0 and y == 1

    def test_top(self):
        ha, va, x, y = self._pos('top')
        assert (ha, va) == ('center', 'top')
        assert x == 0.5 and y == 1

    def test_top_right(self):
        ha, va, x, y = self._pos('top-right')
        assert (ha, va) == ('right', 'top')
        assert x == 1 and y == 1

    def test_left(self):
        ha, va, x, y = self._pos('left')
        assert (ha, va) == ('left', 'center')
        assert x == 0 and y == 0.5

    def test_right(self):
        ha, va, x, y = self._pos('right')
        assert (ha, va) == ('right', 'center')
        assert x == 1 and y == 0.5

    def test_bottom_left(self):
        ha, va, x, y = self._pos('bottom-left')
        assert (ha, va) == ('left', 'bottom')
        assert x == 0 and y == 0

    def test_bottom(self):
        ha, va, x, y = self._pos('bottom')
        assert (ha, va) == ('center', 'bottom')
        assert x == 0.5 and y == 0

    def test_bottom_right(self):
        ha, va, x, y = self._pos('bottom-right')
        assert (ha, va) == ('right', 'bottom')
        assert x == 1 and y == 0


# ---------------------------------------------------------------------------
# Marker.get_label_position
# ---------------------------------------------------------------------------

class MarkerLabelPositionTests(TestCase):
    def _pos(self, position):
        return Marker(geometry=Point(10, 20), label_position=position).get_label_position()

    def test_center(self):
        ha, va, x, y = self._pos('center')
        assert (ha, va) == ('center', 'center')
        assert x == 10 and y == 20

    def test_above(self):
        ha, va, x, y = self._pos('above')
        assert va == 'bottom'
        assert y > 20

    def test_below(self):
        ha, va, x, y = self._pos('below')
        assert va == 'top'
        assert y < 20

    def test_left(self):
        ha, va, x, y = self._pos('left')
        assert ha == 'right'
        assert x < 10

    def test_right(self):
        ha, va, x, y = self._pos('right')
        assert ha == 'left'
        assert x > 10


# ---------------------------------------------------------------------------
# StaticMap
# ---------------------------------------------------------------------------

class StaticMapElementsTests(TestCase):
    def test_areas_and_markers_filtered_correctly(self):
        m = make_map()
        m.add(Area(geometry=CA_POLY))
        m.add(Marker(geometry=CA_POINT))
        assert len(m.areas) == 1
        assert len(m.markers) == 1


class StaticMapRenderTests(TestCase):
    def test_render_raises_with_no_elements(self):
        with pytest.raises(ValueError):
            make_map().render()

    def test_render_polygon_returns_bytes(self):
        m = make_map()
        m.add(Area(geometry=CA_POLY))
        result = m.render(format='png')
        assert isinstance(result, bytes) and len(result) > 0

    def test_render_point_returns_bytes(self):
        m = make_map()
        m.add(Marker(geometry=CA_POINT))
        result = m.render(format='png')
        assert isinstance(result, bytes) and len(result) > 0

    def test_render_jpeg_quality(self):
        m = make_map()
        m.add(Area(geometry=CA_POLY))
        result = m.render(format='jpg', jpeg_quality=50)
        assert isinstance(result, bytes) and len(result) > 0

    def test_render_mixed_elements(self):
        m = make_map()
        m.add(Area(geometry=CA_POLY))
        m.add(Marker(geometry=CA_POINT))
        result = m.render(format='png')
        assert isinstance(result, bytes) and len(result) > 0


# ---------------------------------------------------------------------------
# _compute_extent
# ---------------------------------------------------------------------------

class ComputeExtentTests(TestCase):
    def setUp(self):
        self.m = make_map()
        poly = to_shape(CA_POLY)
        self.series = gpd.GeoSeries([poly], crs=CRS_WEBMERCATOR)

    def test_aspect_ratio_matches_image(self):
        minx, miny, maxx, maxy = self.m._compute_extent(self.series)
        actual = (maxx - minx) / (maxy - miny)
        target = self.m.width / self.m.height
        assert abs(actual - target) < 0.01

    def test_percent_buffer_expands_extent(self):
        unbuffered = self.m._compute_extent(self.series, buffer=0)
        buffered = self.m._compute_extent(self.series, buffer=0.1)
        assert (buffered[2] - buffered[0]) > (unbuffered[2] - unbuffered[0])
        assert (buffered[3] - buffered[1]) > (unbuffered[3] - unbuffered[1])

    def test_single_point_gets_nonzero_extent(self):
        pt = to_shape(CA_POINT)
        series = gpd.GeoSeries([pt], crs=CRS_WEBMERCATOR)
        minx, miny, maxx, maxy = self.m._compute_extent(series)
        assert maxx > minx
        assert maxy > miny


# ---------------------------------------------------------------------------
# from_geometries
# ---------------------------------------------------------------------------

class FromGeometriesTests(TestCase):
    def test_point(self):
        result = from_geometries(CA_POINT, basemap=None, format='png')
        assert isinstance(result, bytes) and len(result) > 0

    def test_polygon(self):
        result = from_geometries(CA_POLY, basemap=None, format='png')
        assert isinstance(result, bytes) and len(result) > 0

    def test_mixed(self):
        result = from_geometries(CA_POLY, CA_POINT, basemap=None, format='png')
        assert isinstance(result, bytes) and len(result) > 0
