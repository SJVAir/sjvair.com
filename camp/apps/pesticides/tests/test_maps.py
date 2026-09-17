from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import maps
from camp.apps.regions.models import Region


class CountyGeometryTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_returns_geojson_per_county(self):
        data = maps.county_geometries()
        assert set(data) == {9001, 9002}
        assert data[9001].startswith('{')
        assert 'MultiPolygon' in data[9001]

    def test_cached(self):
        maps.county_geometries()
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001, 9002}
        cache.clear()
        assert set(maps.county_geometries()) == {9001}

    def test_skips_counties_without_boundary(self):
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001}


class CountyMapTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.rows = [
            {'county_id': 9001, 'county_name': 'Fresno County', 'county_slug': 'fresno', 'lbs': 150.0, 'acres': 15, 'applications': 2},
        ]

    def test_renders_all_counties(self):
        html = maps.county_map(self.rows)
        assert 'admin-leaflet-map' in html
        assert 'Fresno County' in html
        assert 'Kern County' in html      # drawn even with no rows

    def test_shading(self):
        html = maps.county_map(self.rows)
        assert maps.RAMP[-1] in html      # the max county gets the darkest step
        assert maps.NO_DATA in html       # a county with no rows is grey

    def test_ramp_steps(self):
        assert maps.ramp_color(0, 100) == maps.NO_DATA
        assert maps.ramp_color(1, 100) == maps.RAMP[0]
        assert maps.ramp_color(50, 100) == maps.RAMP[2]
        assert maps.ramp_color(100, 100) == maps.RAMP[-1]

    def test_none_without_geometries(self):
        Region.objects.filter(type='county').update(boundary=None)
        assert maps.county_map(self.rows) is None

    def test_labels_include_pounds(self):
        html = maps.county_map(self.rows)
        assert 'Fresno County: 150 lbs' in html
        assert 'Kern County: no data' in html
