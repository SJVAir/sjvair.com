from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions.models import EmissionsRecord, Facility


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


from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache

from camp.apps.regions.models import Boundary, Region


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
