from django.contrib.gis.geos import GEOSGeometry, Point
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.shapes import BUFFERS, BUFFER_LABELS, buffer_options, buffer_param, region_shape
from camp.utils.gis import EPSG_CALIFORNIA_ALBERS, EPSG_LATLON

SQUARE = 'SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))'
MILE = 1609.344


def east_of_edge(meters):
    """A point the given distance (m) east of the square's east edge midpoint."""
    point = Point(-119.75, 36.70, srid=EPSG_LATLON).transform(EPSG_CALIFORNIA_ALBERS, clone=True)
    point.x += meters
    return point.transform(EPSG_LATLON, clone=True)


class BufferParamTests(TestCase):
    def test_valid_values(self):
        assert BUFFERS == (0, 1, 3, 5)
        for miles in BUFFERS:
            assert buffer_param({'buffer': str(miles)}) == miles

    def test_junk_is_zero(self):
        for value in ('', 'abc', '-1', '2', '4', '10', '1.5'):
            assert buffer_param({'buffer': value}) == 0
        assert buffer_param({}) == 0


class RegionShapeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.region = Region.objects.create(
            name='Square', slug='square', type=Region.Type.COUNTY, external_id='sq',
        )
        self.region.boundary = Boundary.objects.create(region=self.region, version='t', geometry=SQUARE)
        self.region.save()

    def test_zero_is_the_boundary(self):
        shape = region_shape(self.region, 0)
        assert shape.srid == EPSG_LATLON
        assert shape.equals(self.region.boundary.geometry)

    def test_buffer_widens(self):
        shape = region_shape(self.region, 1)
        assert shape.srid == EPSG_LATLON
        assert shape.contains(self.region.boundary.geometry)
        assert shape.area > self.region.boundary.geometry.area
        assert shape.contains(east_of_edge(0.9 * MILE))
        assert not shape.contains(east_of_edge(1.1 * MILE))

    def test_buffer_is_cached(self):
        key = f'regions:shape:v1:{self.region.sqid}:3'
        assert cache.get(key) is None
        first = region_shape(self.region, 3)
        assert cache.get(key) is not None
        second = region_shape(self.region, 3)
        assert second.srid == EPSG_LATLON
        assert second.equals(first)

    def test_no_boundary_is_none(self):
        bare = Region.objects.create(name='Bare', slug='bare', type=Region.Type.COUNTY, external_id='bare')
        assert region_shape(bare, 1) is None
        assert region_shape(bare, 0) is None


class BufferOptionsTests(TestCase):
    def test_options(self):
        request = RequestFactory().get('/tools/pesticides/', {'year': '2022', 'page': '3', 'buffer': '1'})
        options = buffer_options(request, 1)
        assert [o['label'] for o in options] == [BUFFER_LABELS[m] for m in BUFFERS]
        assert [o['current'] for o in options] == [False, True, False, False]
        for option in options:
            assert 'year=2022' in option['url']
            assert 'page' not in option['url']
        assert 'buffer' not in options[0]['url']
        assert 'buffer=1' in options[1]['url']
        assert 'buffer=5' in options[3]['url']
