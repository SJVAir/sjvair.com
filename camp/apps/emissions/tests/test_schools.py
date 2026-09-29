from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import schools
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Location

# One degree of latitude is about 364,000 ft, so this places a point `feet` north of another to within ~0.3%.
FEET_PER_DEGREE_LAT = 364_000


def north_of(point, feet):
    return Point(point.x, point.y + feet / FEET_PER_DEGREE_LAT, srid=4326)


def location(name, point, type=Location.Type.PUBLIC_SCHOOL):
    return Location.objects.create(name=name, type=type, external_id=name, source='test', point=point)


class SchoolsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')  # point_source census (trusted)
        self.near = location('NEAR ELEMENTARY', north_of(self.plant.point, 900))
        self.nearer = location('NEARER PRESCHOOL', north_of(self.plant.point, 300), Location.Type.CHILD_CARE)
        self.quarter = location('QUARTER MILE ACADEMY', north_of(self.plant.point, 1200), Location.Type.PRIVATE_SCHOOL)
        self.far = location('FAR HIGH', north_of(self.plant.point, 2000))


class NearTests(SchoolsTestCase):
    def test_two_groups_ordered_by_distance(self):
        result = schools.near(self.plant)
        assert [row['name'] for row in result['within_1000ft']] == ['NEARER PRESCHOOL', 'NEAR ELEMENTARY']
        assert [row['name'] for row in result['within_quarter_mile']] == ['QUARTER MILE ACADEMY']
        near = result['within_1000ft'][1]
        assert 850 < near['feet'] < 950 and isinstance(near['feet'], int)
        assert near['type_label'] == 'Public school' and near['sqid'] == self.near.sqid
        assert abs(near['lat'] - self.near.point.y) < 1e-9 and abs(near['lng'] - self.near.point.x) < 1e-9
        assert result['within_1000ft'][0]['type_label'] == 'Child care'
        assert 1150 < result['within_quarter_mile'][0]['feet'] < 1250

    def test_nothing_nearby(self):
        Location.objects.exclude(pk=self.far.pk).delete()
        assert schools.near(self.plant) == {'within_1000ft': [], 'within_quarter_mile': []}

    def test_cached_per_facility(self):
        schools.near(self.plant)
        location('LATECOMER', north_of(self.plant.point, 500))
        assert 'LATECOMER' not in [row['name'] for row in schools.near(self.plant)['within_1000ft']]
        cache.clear()
        assert 'LATECOMER' in [row['name'] for row in schools.near(self.plant)['within_1000ft']]

    def test_geojson_lists_the_shown_rows(self):
        collection = schools.geojson(schools.near(self.plant))
        assert collection['type'] == 'FeatureCollection'
        names = {feature['properties']['name']: feature for feature in collection['features']}
        assert set(names) == {'NEARER PRESCHOOL', 'NEAR ELEMENTARY', 'QUARTER MILE ACADEMY'}
        assert names['NEAR ELEMENTARY']['properties']['group'] == 'notice'
        assert names['QUARTER MILE ACADEMY']['properties']['group'] == 'quarter'
        assert names['NEAR ELEMENTARY']['geometry'] == {'type': 'Point', 'coordinates': [self.near.point.x, self.near.point.y]}

    def test_geojson_stops_at_the_shown_count(self):
        for i in range(12):
            location(f'CROWD {i}', north_of(self.plant.point, 400 + i))
        result = schools.near(self.plant)
        assert len(result['within_1000ft']) == 14
        assert len(schools.geojson(result)['features']) == schools.SHOWN + 1


class HiddenTests(SchoolsTestCase):
    def test_untrusted_or_missing_point(self):
        for source in (Facility.PointSource.MAPTILER, Facility.PointSource.LEGACY, ''):
            self.plant.point_source = source
            assert schools.near(self.plant) is None, source
        self.plant.point_source = Facility.PointSource.CENSUS
        self.plant.point = None
        assert schools.near(self.plant) is None

    def test_oil_gas_and_refining_sectors(self):
        for sector in (Facility.Sector.OIL_GAS, Facility.Sector.REFINING_FUELS):
            self.plant.sector = sector
            assert schools.near(self.plant) is None, sector
        self.plant.sector = Facility.Sector.GLASS
        assert schools.near(self.plant) is not None

    def test_ungeocodable_address(self):
        self.plant.address = {'street': 'VARIOUS LOCATIONS', 'city': 'FRESNO', 'zipcode': ''}
        assert schools.near(self.plant) is None
        self.plant.address = {}
        assert schools.near(self.plant) is None
