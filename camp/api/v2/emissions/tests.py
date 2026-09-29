import tempfile
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from camp.apps.emissions import areas, carbonmapper, dairies, methane, wells
from camp.apps.emissions.models import DairyHerd, Digester, EmissionsRecord, Facility, MethanePlume, MethaneSource, ToxicEmission, ToxicPollutant, Well
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, SAMPLE_PNG, plume_item, row
from camp.apps.emissions.tests.test_dairies import IN_KERN, dairy_inventory, make_dairies, set_city
from camp.apps.emissions.tests.test_wells import make_well
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
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': 1, 'pollutant': 'benzene'})
        body = response.json()
        assert body['properties'] == {'year': 2024, 'pollutant': 'benzene', 'label': 'Benzene', 'unit': 'lbs', 'compare': None}
        plant = [f for f in body['features'] if f['properties']['name'] == 'TEST PLANT'][0]
        assert plant['properties']['value'] == 2.0

    def test_compare(self):
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023})
        body = response.json()
        assert body['properties']['compare'] == 2023
        by_name = {f['properties']['name']: f['properties'] for f in body['features']}
        # TEST PLANT has a 2023 record; TEST CEMENT doesn't (test_specific_year).
        assert by_name['TEST PLANT']['value_prev'] is not None
        assert by_name['TEST CEMENT']['value_prev'] is None

    def test_compare_ignores_the_scope_year_and_an_unloaded_year(self):
        for bad in (2024, 1999, 'garbage'):
            response = self.client.get(reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': bad})
            body = response.json()
            assert body['properties']['compare'] is None
            assert all('value_prev' not in f['properties'] for f in body['features'])

    def test_compare_with_a_sector_filter(self):
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023, 'sector': 'glass'})
        body = response.json()
        assert [f['properties']['name'] for f in body['features']] == ['TEST PLANT']
        assert body['features'][0]['properties']['value_prev'] == 3.0

    def test_compare_below_the_small_baseline_floor_is_not_comparable(self):
        # TEST CEMENT reported 0 NOx in 2023: too small a baseline for a
        # percent change to mean anything (stats.SMALL_BASELINE_FLOOR).
        EmissionsRecord.objects.create(facility=Facility.objects.get(name='TEST CEMENT'), year=2023, nox='0')
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023})
        body = response.json()
        cement = [f for f in body['features'] if f['properties']['name'] == 'TEST CEMENT'][0]
        assert cement['properties']['value_prev'] is None

    def test_compare_below_the_floor_with_a_nonzero_baseline(self):
        # 0.5 tons NOx in 2023 is nonzero but still under the 1.0 ton/yr
        # floor (unlike the all-zero case above).
        EmissionsRecord.objects.create(facility=Facility.objects.get(name='TEST CEMENT'), year=2023, nox='0.5')
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023})
        body = response.json()
        cement = [f for f in body['features'] if f['properties']['name'] == 'TEST CEMENT'][0]
        assert cement['properties']['value_prev'] is None

    def test_compare_floor_uses_the_toxics_lbs_threshold(self):
        # Toxics floor at 1 lb/yr, not the criteria pollutants' 1 ton/yr:
        # 0.5 lbs is under it, 5 lbs clears it.
        plant = Facility.objects.get(name='TEST PLANT')
        benzene = ToxicPollutant.objects.get(slug='benzene')
        ToxicEmission.objects.filter(facility=plant, year=2023, pollutant=benzene).update(lbs='0.5')
        response = self.client.get(
            reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023, 'toxics': 1, 'pollutant': 'benzene'})
        body = response.json()
        assert body['properties']['unit'] == 'lbs'
        plant_props = [f for f in body['features'] if f['properties']['name'] == 'TEST PLANT'][0]['properties']
        assert plant_props['value_prev'] is None

        ToxicEmission.objects.filter(facility=plant, year=2023, pollutant=benzene).update(lbs='5')
        cache.clear()
        response = self.client.get(
            reverse('api:v2:emissions:geojson'), {'year': 2024, 'compare': 2023, 'toxics': 1, 'pollutant': 'benzene'})
        plant_props = [f for f in response.json()['features'] if f['properties']['name'] == 'TEST PLANT'][0]['properties']
        assert plant_props['value_prev'] == 5.0

    def test_weighted_measure_is_a_share(self):
        data = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': '1', 'minor': '1'}).json()
        assert data['properties']['unit'] == 'share' and data['properties']['pollutant'] == 'cancer'
        values = {f['properties']['name']: f['properties']['value'] for f in data['features']}
        assert abs(sum(values.values()) - 1.0) < 1e-9 and values['TEST CEMENT'] > 0.9
        old = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': '1', 'pollutant': 'benzene'}).json()
        assert old['properties']['unit'] == 'lbs' and old['properties']['pollutant'] == 'benzene'

    def test_filters(self):
        assert len(self.features(minor=1)) == 3
        assert [f['properties']['name'] for f in self.features(sector='glass')] == ['TEST PLANT']
        assert [f['properties']['name'] for f in self.features(county='fresno')] == ['TEST PLANT']

    def test_facilities_without_a_point_are_left_out(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        assert [f['properties']['name'] for f in self.features()] == ['TEST CEMENT']

    def test_ammonia_in_tons(self):
        body = self.client.get(reverse('api:v2:emissions:geojson'), {'pollutant': 'nh3'}).json()
        assert body['properties']['pollutant'] == 'nh3' and body['properties']['unit'] == 'tons'
        values = {f['properties']['name']: f['properties']['value'] for f in body['features']}
        assert values['TEST PLANT'] == 0.05 and values['TEST CEMENT'] is None


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

    def test_compare(self):
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'year': '2024', 'compare': '2023'})
        data = response.json()
        assert data['compare'] == 2023
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        area = next(a for a in data['areas'] if a['id'] == fresno.sqid)
        assert {'total_prev', 'per_sq_mi_prev', 'per_1k_residents_prev'} <= set(area)
        # TEST PLANT, Fresno's only facility here, reported 3.0 tons NOx in
        # 2023 -- the compared year's sum.
        assert area['total_prev'] == 3.0

    def test_compare_below_the_small_baseline_floor_is_not_comparable(self):
        # Kern's compared-year (2023) NOx sum is 0 (TEST CEMENT has no 2023
        # record; TEST GAS STATION's does, but reports rog/tog, not nox) --
        # too small a baseline for a percent change to mean anything.
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'year': '2024', 'compare': '2023'})
        data = response.json()
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        area = next(a for a in data['areas'] if a['id'] == kern.sqid)
        assert area['total'] == 100.0
        assert area['total_prev'] is None

    def test_compare_below_the_floor_with_a_nonzero_baseline(self):
        # 0.5 tons NOx in 2023 is nonzero but still under the 1.0 ton/yr floor.
        EmissionsRecord.objects.create(facility=Facility.objects.get(name='TEST CEMENT'), year=2023, nox='0.5')
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'year': '2024', 'compare': '2023'})
        data = response.json()
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        area = next(a for a in data['areas'] if a['id'] == kern.sqid)
        assert area['total_prev'] is None

    def test_compare_floor_uses_the_toxics_lbs_threshold(self):
        # Fresno's only facility here (TEST PLANT) at a toxics floor of 1
        # lb/yr, not the criteria pollutants' 1 ton/yr: 0.5 lbs is under it,
        # 5 lbs clears it.
        plant = Facility.objects.get(name='TEST PLANT')
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        benzene = ToxicPollutant.objects.get(slug='benzene')
        ToxicEmission.objects.filter(facility=plant, year=2023, pollutant=benzene).update(lbs='0.5')
        response = self.client.get(
            reverse('api:v2:emissions:areas'),
            {'level': 'county', 'year': '2024', 'compare': '2023', 'toxics': 1, 'pollutant': 'benzene'})
        data = response.json()
        assert data['unit'] == 'lbs'
        area = next(a for a in data['areas'] if a['id'] == fresno.sqid)
        assert area['total_prev'] is None

        ToxicEmission.objects.filter(facility=plant, year=2023, pollutant=benzene).update(lbs='5')
        cache.clear()
        response = self.client.get(
            reverse('api:v2:emissions:areas'),
            {'level': 'county', 'year': '2024', 'compare': '2023', 'toxics': 1, 'pollutant': 'benzene'})
        area = next(a for a in response.json()['areas'] if a['id'] == fresno.sqid)
        assert area['total_prev'] == 5.0

    def test_weighted_measure_is_a_share(self):
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'toxics': '1', 'minor': '1'})
        data = response.json()
        assert data['unit'] == 'share'
        assert abs(sum(area['total'] for area in data['areas']) - 1.0) < 1e-9

    def test_compare_ignores_the_scope_year(self):
        response = self.client.get(reverse('api:v2:emissions:areas'), {'level': 'county', 'year': '2024', 'compare': '2024'})
        data = response.json()
        assert data['compare'] is None and 'total_prev' not in data['areas'][0]


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

    def test_region_narrows_by_the_same_rule_as_the_table(self):
        # Plantville's boundary holds BIG DAIRY by point; SMALL DAIRY (Kern)
        # counts in it by mailing city, though its point is far outside.
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        set_city(self.small, 'Plantville')
        dairies.clear_caches()
        names = [f['properties']['name'] for f in self.get('dairy-geojson', {'region': cdp.sqid}).json()['features']]
        assert names == [herd.dairy.name for herd in dairies.table(2023, area=areas.RegionArea(cdp))]
        assert set(names) == {'BIG DAIRY', 'SMALL DAIRY'}
        county = self.get('dairy-geojson', {'region': self.fresno.sqid}).json()['features']
        assert [f['properties']['name'] for f in county] == ['BIG DAIRY']

    def test_a_point_narrows_to_its_radius(self):
        near = self.get('dairy-geojson', {'lat': '36.737', 'lng': '-119.787', 'radius': '1'}).json()['features']
        assert [f['properties']['name'] for f in near] == ['BIG DAIRY']

    def test_unknown_region_and_bad_point_are_400(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        for params in ({'region': 'nope'}, {'region': retired.sqid}, {'lat': 'x', 'lng': '1'},
                       {'lat': '36.7', 'lng': '-119.7', 'radius': '2'}, {'lat': '91', 'lng': '0'}):
            response = self.get('dairy-geojson', params)
            assert response.status_code == 400 and 'error' in response.json(), params

    def test_area_responses_are_cached_apart(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'MISS'
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'HIT'
        assert self.get('dairy-geojson')['X-Cache-Status'] == 'MISS'
        dairies.clear_caches()
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'MISS'

    def test_counties(self):
        dairy_inventory(self.fresno, rog=2.0)
        response = self.get('dairy-counties', {'year': 2023, 'pollutant': 'rog', 'measure': 'mature_cows'})
        assert response.status_code == 200
        body = response.json()
        assert (body['pollutant'], body['label'], body['unit'], body['measure']) == ('rog', 'ROG', 'tons', 'mature_cows')
        assert body['source'] == 'CARB county inventory, dairy cattle: animals and manure only, not feed or silage'
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

    def test_detail_with_an_unknown_digester_start_year(self):
        # A handful of CADD's AgSTAR digesters carry no recorded start year.
        Digester.objects.create(dairy=self.big, operational_year=None, shutdown_year=None, source='AgSTAR')
        body = self.get('dairy-detail', sqid=self.big.sqid).json()
        digester = next(d for d in body['digesters'] if d['source'] == 'AgSTAR')
        assert digester == {'operational_year': None, 'shutdown_year': None, 'source': 'AgSTAR', 'operating': True}

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

    def test_detail_carries_the_methane_block(self):
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH, rate='120', unc='40')])
        block = self.get('dairy-detail', sqid=self.big.sqid).json()['methane']
        assert [s['rate_text'] for s in block['sources']] == ['120 ± 40 kg/h']
        assert block['sources'][0]['viewer_url'].startswith('https://data.carbonmapper.org/#')
        assert 'attribution' not in block  # the popup draws it from the map's own config
        assert self.get('dairy-detail', sqid=self.small.sqid).json()['methane']['sources'] == []


class WellEndpointTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.active = make_well('0402900001', IN_KERN, kern, spud_date='2015-03-04')
        self.idle = make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), kern, status='Idle', hpz='Verified HPZ', directional=True)

    def test_geojson_is_compact_rows(self):
        response = self.client.get(reverse('api:v2:emissions:wells-geojson'))
        assert response.status_code == 200 and response['Content-Type'] == 'application/json'
        body = response.json()
        assert body['imported'] is None and body['statuses'] == ['Active', 'Idle', 'New']
        by_id = {row[0]: row for row in body['wells']}
        assert by_id[self.idle.sqid] == [self.idle.sqid, round(IN_KERN[0] + 0.001, 5), IN_KERN[1], 1, 1]
        assert by_id[self.active.sqid][3:] == [0, 0]

    def test_geojson_cache_follows_the_wells_generation_and_holds_compressed_bytes(self):
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['wells']) == 2
        assert isinstance(cache.get(wells.key('geojson')), bytes)  # zlib: small enough for memcached
        Well.objects.filter(pk=self.idle.pk).delete()
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['wells']) == 2
        wells.clear_caches()
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['wells']) == 1

    def test_detail(self):
        body = self.client.get(reverse('api:v2:emissions:well-detail', args=[self.idle.sqid])).json()
        assert body == {
            'id': self.idle.sqid, 'api': '0402900002', 'label': 'TEST LEASE 02', 'lease_name': 'TEST LEASE', 'well_number': '02',
            'status': 'Idle', 'well_type': 'Oil & Gas', 'operator': 'TEST OIL LLC', 'field': 'Test Field', 'county': 'Kern County',
            'spud_year': None, 'in_hpz': 'Verified HPZ', 'directional': True, 'url': self.idle.calgem_url,
        }
        assert self.client.get(reverse('api:v2:emissions:well-detail', args=[self.active.sqid])).json()['spud_year'] == 2015
        assert self.client.get(reverse('api:v2:emissions:well-detail', args=['nope'])).status_code == 404


class MethaneEndpointTests(TestCase):
    """
    /api/2.0/emissions/methane/: what used to be the same-origin-only
    /tools/emissions/methane/geojson/ (test_methane.py's ViewTests), now
    public, plus the source plumes endpoint the map's popup stepper reads.
    """
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.mkdtemp()
        self._media_root = override_settings(MEDIA_ROOT=self.tmp)
        self._media_root.enable()
        self.addCleanup(self._media_root.disable)
        carbonmapper.apply([row(name='near', lnglat=NEAR_BOTH)])
        self.source = MethaneSource.objects.get(source_name='near')

    def test_geojson_is_lean(self):
        response = self.client.get(reverse('api:v2:emissions:methane-geojson'))
        assert response.status_code == 200
        body = response.json()
        assert body['type'] == 'FeatureCollection' and len(body['features']) == 1
        # Attribution is on the pages and the map, not repeated in the payload.
        assert set(body['properties']) == {'sources', 'imported'}

    def test_geojson_is_404_before_any_import(self):
        MethaneSource.objects.all().delete()
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.filter(source='carbon-mapper').delete()
        methane.clear_caches()
        assert self.client.get(reverse('api:v2:emissions:methane-geojson')).status_code == 404

    def test_geojson_cache_follows_the_methane_generation(self):
        assert self.client.get(reverse('api:v2:emissions:methane-geojson'))['X-Cache-Status'] == 'MISS'
        assert self.client.get(reverse('api:v2:emissions:methane-geojson'))['X-Cache-Status'] == 'HIT'
        carbonmapper.apply([row(name='near', lnglat=NEAR_BOTH), row(name='second', lnglat=(-119.0, 35.4))])
        response = self.client.get(reverse('api:v2:emissions:methane-geojson'))
        assert response['X-Cache-Status'] == 'MISS' and len(response.json()['features']) == 2

    def test_plumes_newest_first_with_bounds_and_image_url(self):
        with patch('camp.apps.emissions.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            carbonmapper.apply_plumes([
                plume_item(plume_id='older', lnglat=NEAR_BOTH, scene_timestamp='2026-01-01T00:00:00.000Z',
                           rate=100, unc=20, wind_speed=1.5, wind_dir=90, bounds=[-119.79, 36.73, -119.78, 36.74]),
                plume_item(plume_id='newer', lnglat=NEAR_BOTH, scene_timestamp='2026-06-01T00:00:00.000Z',
                           rate=200, unc=None, wind_speed=None, wind_dir=None),
            ])
        response = self.client.get(reverse('api:v2:emissions:methane-plumes', args=[self.source.sqid]))
        assert response.status_code == 200
        body = response.json()
        assert [p['id'] for p in body['plumes']] == [MethanePlume.objects.get(plume_id='newer').sqid, MethanePlume.objects.get(plume_id='older').sqid]
        older = body['plumes'][1]
        assert older['rate'] == 100.0 and older['uncertainty'] == 20.0 and older['rate_text'] == '100 ± 20 kg/h'
        assert older['wind_speed'] == 1.5 and older['wind_direction'] == 90.0
        assert older['bounds'] == [[-119.79, 36.74], [-119.78, 36.74], [-119.78, 36.73], [-119.79, 36.73]]
        assert older['image_url'] and older['image_url'].startswith('/')
        newer = body['plumes'][0]
        assert newer['uncertainty'] is None and newer['wind_speed'] is None and newer['rate_text'] == '200 kg/h'
        assert set(body) == {'source', 'plumes'}
        assert body['source'] == self.source.sqid

    def test_plume_with_no_image_is_null(self):
        with patch('camp.apps.emissions.carbonmapper.fetch_plume_image', return_value=None):
            carbonmapper.apply_plumes([plume_item(plume_id='noimg', lnglat=NEAR_BOTH)])
        body = self.client.get(reverse('api:v2:emissions:methane-plumes', args=[self.source.sqid])).json()
        assert body['plumes'][0]['image_url'] is None

    def test_unknown_source_is_404(self):
        response = self.client.get(reverse('api:v2:emissions:methane-plumes', args=['doesnotexist']))
        assert response.status_code == 404

    def test_source_with_no_plumes_is_empty(self):
        MethanePlume.objects.all().delete()
        body = self.client.get(reverse('api:v2:emissions:methane-plumes', args=[self.source.sqid])).json()
        assert body['plumes'] == []

    def test_plumes_cache_follows_the_methane_generation(self):
        # import_carbon_mapper always runs apply() (which bumps the
        # generation) before apply_plumes() in the same command invocation,
        # so a real import's new plumes are never served from a stale cache.
        url = reverse('api:v2:emissions:methane-plumes', args=[self.source.sqid])
        assert self.client.get(url)['X-Cache-Status'] == 'MISS'
        assert self.client.get(url)['X-Cache-Status'] == 'HIT'
        carbonmapper.apply([row(name='near', lnglat=NEAR_BOTH)])
        with patch('camp.apps.emissions.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            carbonmapper.apply_plumes([plume_item(plume_id='fresh', lnglat=NEAR_BOTH)])
        response = self.client.get(url)
        assert response['X-Cache-Status'] == 'MISS' and len(response.json()['plumes']) == 1
