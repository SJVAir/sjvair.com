import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import dairies
from camp.apps.emissions.models import DairyHerd, EmissionsRecord, Facility
from camp.apps.emissions.tests.test_dairies import dairy_inventory, make_dairies
from camp.apps.regions.models import Boundary, Region


class FacilityListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def names(self, **params):
        response = self.client.get(reverse('api:v2:emissions:list'), params)
        assert response.status_code == 200
        return [row['name'] for row in response.json()['data']]

    def test_defaults_to_the_latest_year(self):
        response = self.client.get(reverse('api:v2:emissions:list'))
        data = response.json()['data']
        assert {row['name'] for row in data} == {'TEST PLANT', 'TEST GAS STATION', 'TEST CEMENT'}
        assert {row['emissions']['year'] for row in data} == {2024}

    def test_specific_year(self):
        assert set(self.names(year=2023)) == {'TEST PLANT', 'TEST GAS STATION'}

    def test_invalid_year_returns_empty_list(self):
        assert self.names(year='garbage') == []

    def test_sources(self):
        assert set(self.names(sources='major')) == {'TEST PLANT', 'TEST CEMENT'}
        assert self.names(sources='minor') == ['TEST GAS STATION']

    def test_region_filters(self):
        assert self.names(county='fresno') == ['TEST PLANT']
        assert self.names(city='fresno') == ['TEST PLANT']
        assert self.names(zipcode='93728') == ['TEST PLANT']

    def test_carries_district_and_total_pm(self):
        response = self.client.get(reverse('api:v2:emissions:list'), {'county': 'fresno'})
        row = response.json()['data'][0]
        assert row['air_district'] == 'San Joaquin Valley APCD'
        assert row['emissions']['pm'] is not None
        assert 'pm25' not in row['emissions']

    def test_excludes_facilities_without_a_point(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        assert 'TEST PLANT' not in self.names()

    def test_blank_year_defaults_to_the_latest_year(self):
        response = self.client.get(reverse('api:v2:emissions:list'), {'year': ''})
        data = response.json()['data']
        assert {row['name'] for row in data} == {'TEST PLANT', 'TEST GAS STATION', 'TEST CEMENT'}
        assert {row['emissions']['year'] for row in data} == {2024}

    def test_facility_without_a_record_in_the_requested_year_is_excluded(self):
        # TEST CEMENT has no 2023 record.
        assert 'TEST CEMENT' not in self.names(year=2023)

    def test_blank_year_does_not_500_when_a_pointed_facility_has_no_records_at_all(self):
        sju = Facility.objects.get(name='TEST PLANT').air_district
        Facility.objects.create(
            county_code=10, air_district=sju, facid=99, name='TEST NO RECORDS',
            point=Point(-119.787, 36.737), county_id=3,
        )
        response = self.client.get(reverse('api:v2:emissions:list'), {'year': ''})
        assert response.status_code == 200
        assert 'TEST NO RECORDS' not in [row['name'] for row in response.json()['data']]


class YearListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_distinct_years_descending(self):
        response = self.client.get(reverse('api:v2:emissions:years'))
        assert response.json()['data'] == [2024, 2023]

    def test_empty(self):
        EmissionsRecord.objects.all().delete()
        response = self.client.get(reverse('api:v2:emissions:years'))
        assert response.json()['data'] == []


class FacilityDetailTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_full_history_newest_first(self):
        facility = Facility.objects.get(name='TEST PLANT')
        response = self.client.get(reverse('api:v2:emissions:detail', kwargs={'facility_id': facility.sqid}))
        data = response.json()['data']
        assert data['name'] == 'TEST PLANT'
        assert [row['year'] for row in data['emissions']] == [2024, 2023]

    def test_unknown_sqid_is_404(self):
        response = self.client.get(reverse('api:v2:emissions:detail', kwargs={'facility_id': 'doesnotexist'}))
        assert response.status_code == 404


class FacilityGeoJSONTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def features(self, **params):
        response = self.client.get(reverse('api:v2:emissions:geojson'), params)
        assert response.status_code == 200
        return response.json()['features']

    def test_scope(self):
        features = self.features()
        assert [f['properties']['name'] for f in features] == ['TEST CEMENT', 'TEST PLANT']
        cement = features[0]
        assert cement['geometry'] == {'type': 'Point', 'coordinates': [-118.17, 35.05]}
        assert cement['properties']['value'] == 100.0
        assert cement['properties']['rank'] == 1
        assert cement['properties']['sector'] == 'Cement, concrete & minerals'
        assert cement['properties']['id'] == Facility.objects.get(name='TEST CEMENT').sqid

    def test_collection_properties(self):
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': 1})
        body = response.json()
        assert body['properties'] == {'year': 2024, 'pollutant': 'benzene', 'label': 'Benzene', 'unit': 'lbs'}
        plant = [f for f in body['features'] if f['properties']['name'] == 'TEST PLANT'][0]
        assert plant['properties']['value'] == 2.0

    def test_filters(self):
        assert len(self.features(minor=1)) == 3
        assert [f['properties']['name'] for f in self.features(sector='glass')] == ['TEST PLANT']
        assert [f['properties']['name'] for f in self.features(county='fresno')] == ['TEST PLANT']

    def test_facilities_without_a_point_are_left_out(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        assert [f['properties']['name'] for f in self.features()] == ['TEST CEMENT']


class DistrictListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_districts_with_facilities_and_boundaries(self):
        cache.clear()
        sju = Region.objects.get(pk=9001)
        sju.boundary = Boundary.objects.create(
            region=sju, version='test',
            geometry=MultiPolygon(Polygon.from_bbox((-121, 35, -118, 38)), srid=4326),
        )
        sju.save(update_fields=['boundary'])
        response = self.client.get(reverse('api:v2:emissions:districts'))
        features = response.json()['features']
        assert [f['properties']['code'] for f in features] == ['SJU']
        assert features[0]['properties']['name'] == 'San Joaquin Valley APCD'
        assert features[0]['geometry']['type'] in ('Polygon', 'MultiPolygon')


class AreaValuesEndpointTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def test_county_values(self):
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'year': '2024'})
        assert response.status_code == 200
        data = response.json()
        assert data['level'] == 'county' and data['unit'] == 'tons'
        assert {area['facilities'] for area in data['areas']} >= {1}
        assert set(data['areas'][0]) == {'id', 'facilities', 'total', 'per_sq_mi', 'per_1k_residents'}

    def test_level_is_required_and_checked(self):
        assert self.client.get(reverse('api:v2:emissions:areas')).status_code == 400
        assert self.client.get(reverse('api:v2:emissions:areas'), {'level': 'mtrs'}).status_code == 400


class DairyEndpointTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def get(self, name, params=None, **kwargs):
        return self.client.get(reverse(f'api:v2:emissions:{name}', kwargs=kwargs or None), params or {})

    def test_geojson(self):
        response = self.get('dairy-geojson')
        assert response.status_code == 200
        body = response.json()
        assert body['properties'] == {'year': 2023, 'size_classes': dairies.size_classes()}
        assert [size['key'] for size in body['properties']['size_classes']] == ['large', 'medium', 'small']
        features = body['features']
        assert [f['properties']['name'] for f in features] == ['BIG DAIRY', 'SMALL DAIRY']
        big = features[0]
        assert big['id'] == self.big.sqid
        assert big['geometry'] == {'type': 'Point', 'coordinates': [-119.785, 36.735]}
        assert big['properties'] == {
            'id': self.big.sqid, 'name': 'BIG DAIRY', 'mature_cows': 1300, 'other_cattle': 300,
            'size_class': 'large', 'digester': True, 'county': 'fresno',
        }
        small = features[1]['properties']
        assert (small['size_class'], small['mature_cows'], small['other_cattle'], small['digester']) == ('small', 100, 50, False)

    def test_geojson_leaves_out_empty_herds(self):
        names = [f['properties']['name'] for f in self.get('dairy-geojson', {'year': 2023}).json()['features']]
        assert 'CLOSED DAIRY' not in names
        assert [f['properties']['name'] for f in self.get('dairy-geojson', {'year': 2022}).json()['features']] == ['BIG DAIRY']

    def test_an_invalid_year_is_a_400(self):
        for year in ('1999', 'x'):
            response = self.get('dairy-geojson', {'year': year})
            assert response.status_code == 400 and 'error' in response.json()
            assert self.get('dairy-counties', {'year': year}).status_code == 400
            assert self.get('dairy-detail', {'year': year}, sqid=self.big.sqid).status_code == 400

    def test_cached_until_a_reimport(self):
        assert self.get('dairy-geojson')['X-Cache-Status'] == 'MISS'
        assert self.get('dairy-geojson')['X-Cache-Status'] == 'HIT'
        dairies.clear_caches()
        assert self.get('dairy-geojson')['X-Cache-Status'] == 'MISS'

    def test_counties(self):
        dairy_inventory(self.fresno, rog=2.0)
        response = self.get('dairy-counties', {'year': 2023, 'pollutant': 'rog', 'measure': 'mature_cows'})
        assert response.status_code == 200
        body = response.json()
        assert (body['pollutant'], body['label'], body['unit'], body['measure']) == ('rog', 'ROG', 'tons', 'mature_cows')
        assert body['source'] == 'CARB county inventory, dairy cattle waste; silage not included'
        assert len(body['counties']) == 8
        fresno = next(row for row in body['counties'] if row['slug'] == 'fresno')
        assert set(fresno) == {'id', 'slug', 'name', 'emissions', 'emissions_per_sq_mi', 'mature_cows', 'mature_cows_per_sq_mi', 'value'}
        assert fresno['emissions'] == pytest.approx(730)
        assert fresno['value'] == fresno['mature_cows'] == 1300
        assert self.get('dairy-counties')['X-Cache-Status'] == 'MISS'
        assert self.get('dairy-counties').json()['pollutant'] == 'rog'

    def test_counties_reject_what_dairies_dont_report(self):
        for params in ({'pollutant': 'nox'}, {'pollutant': 'benzene'}, {'measure': 'bogus'}):
            response = self.get('dairy-counties', params)
            assert response.status_code == 400 and 'error' in response.json(), params

    def test_detail(self):
        DairyHerd.objects.filter(dairy=self.big, year=2023).update(milk_cows_ref_code='2a')
        response = self.get('dairy-detail', sqid=self.big.sqid)
        assert response.status_code == 200
        body = response.json()
        assert (body['id'], body['name'], body['county'], body['year']) == (self.big.sqid, 'BIG DAIRY', 'Fresno County', 2023)
        assert body['address'] == {'street': '1 Dairy Rd', 'city': 'Riverdale', 'zipcode': '93656'}
        herd = body['herd']
        assert (herd['mature_cows'], herd['other_cattle'], herd['size_class'], herd['size_label']) == (1300, 300, 'large', 'Large')
        assert set(herd) == {'mature_cows', 'other_cattle', 'size_class', 'size_label', 'classes'}
        classes = {row['key']: row for row in body['herd']['classes']}
        assert classes['milk_cows'] == {'key': 'milk_cows', 'label': 'Milk cows', 'count': 1100, 'estimated': True}
        assert classes['dry_cows']['estimated'] is False
        assert classes['beef_cattle']['count'] is None
        assert body['digesters'] == [{'operational_year': 2019, 'shutdown_year': None, 'source': 'DDRDP', 'operating': True}]
        assert body['areas'][0] == {'label': 'Fresno County', 'url': self.fresno.get_emissions_url()}

    def test_detail_in_a_year_without_a_herd(self):
        body = self.get('dairy-detail', {'year': 2022}, sqid=self.small.sqid).json()
        assert body['herd'] is None
        # SMALL's digester shut down in 2021.
        assert body['digesters'] == [{'operational_year': 2015, 'shutdown_year': 2021, 'source': 'DDRDP', 'operating': False}]
        assert self.get('dairy-detail', sqid='doesnotexist').status_code == 404

    def test_no_data_yet_is_empty_not_an_error(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        response = self.get('dairy-geojson')
        assert response.status_code == 200 and response.json()['features'] == []
        assert self.get('dairy-counties').status_code == 200
