import json
from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GEOSGeometry, Point
from django.core.cache import cache
from django.core.cache.backends.base import memcache_key_warnings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.test import Client, TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.regions.endpoints import LocationList, RegionDetail, RegionGeoJSON, RegionList, RegionMetaEndpoint
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.regions.models import Boundary, Location, Region
from camp.apps.regions.resolve import regions_containing, round_point
from camp.apps.regions.tests.test_resolve import make_region as make_square_region
from camp.utils.test import get_response_data

User = get_user_model()

region_list = RegionList.as_view()
region_detail = RegionDetail.as_view()
region_meta = RegionMetaEndpoint.as_view()
region_geojson = RegionGeoJSON.as_view()
location_list = LocationList.as_view()


class RegionListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_returns_200(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        assert response.status_code == 200

    def test_list_fields(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert set(data['data'][0].keys()) == {'id', 'name', 'slug', 'type', 'boundary', 'external_id', 'retired'}

    def test_list_boundary_omits_geometry(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        boundaries = [r['boundary'] for r in data['data'] if r['boundary'] is not None]
        assert len(boundaries) > 0
        for boundary in boundaries:
            assert set(boundary.keys()) == {'id', 'version', 'bbox'}
            assert 'geometry' not in boundary

    def test_list_boundary_keeps_bbox(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        region = next(r for r in data['data'] if r['boundary'] is not None)
        expected = Region.objects.get(sqid=region['id'])
        assert region['boundary']['bbox'] == list(expected.boundary.geometry.extent)

    def test_filter_by_type(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'county'})
        response = region_list(request)
        data = get_response_data(response)
        assert all(r['type'] == 'county' for r in data['data'])

    def test_filter_by_invalid_type_returns_empty(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'nonexistent'})
        response = region_list(request)
        data = get_response_data(response)
        assert data['data'] == []

    def test_filter_by_name(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'name': 'fresno'})
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert all('fresno' in r['name'].lower() for r in data['data'])

    def test_filter_by_slug(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'slug': 'fresno'})
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert all(r['slug'] == 'fresno' for r in data['data'])


class RegionMetaTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def _fetch_region_meta(self):
        url = reverse('api:v2:regions:region-meta')
        request = self.factory.get(url)
        response = region_meta(request)
        return response, get_response_data(response)

    def test_returns_200(self):
        response, content = self._fetch_region_meta()
        assert response.status_code == 200

    def test_includes_every_region_type(self):
        response, content = self._fetch_region_meta()
        assert set(content['data']['types'].keys()) == set(Region.Type.values)

    def test_type_fields(self):
        response, content = self._fetch_region_meta()
        county = content['data']['types']['county']
        assert county == {
            'type': 'county',
            'label': 'County',
            'category': 'administrative',
            'count': 0,
            'parents': [],
            'referenceable': True,
            'browsable': True,
        }

    def test_browsable(self):
        response, content = self._fetch_region_meta()
        types = content['data']['types']
        assert {t for t, info in types.items() if not info['browsable']} == {'mtrs', 'land_use'}

    def test_meta_counts_parents_referenceable(self):
        make_county('Fresno County', FRESNO_COUNTY_WKT)
        make_county('Kern County', KERN_COUNTY_WKT)
        retired = make_county('Old County', ELSEWHERE_WKT)
        retired.retired_at = timezone.now()
        retired.save(update_fields=['retired_at'])
        response, content = self._fetch_region_meta()
        types = content['data']['types']
        assert types['county']['count'] == Region.objects.filter(type='county').count() == 2
        assert types['zipcode']['parents'] == ['county']
        assert types['county']['parents'] == []
        assert types['land_use']['referenceable'] is False
        assert types['zipcode']['referenceable'] is True

    def test_category_matches_model_mapping(self):
        response, content = self._fetch_region_meta()
        for region_type, category in Region.TYPE_CATEGORIES.items():
            assert content['data']['types'][region_type]['category'] == category.value


class RegionDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def test_detail_returns_200(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        assert response.status_code == 200

    def test_detail_has_geometry(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        assert data['data']['boundary'] is not None
        assert data['data']['boundary']['geometry'] is not None

    def test_buffer_widens_the_boundary_geometry(self):
        def area(**params):
            response = region_detail(self.factory.get('/', params), region_id=self.region.sqid)
            geometry = get_response_data(response)['data']['boundary']['geometry']
            return GEOSGeometry(json.dumps(geometry)).area
        assert area(buffer=3) > area()
        assert area(buffer=5) > area(buffer=3)
        response = region_detail(self.factory.get('/', {'buffer': 7}), region_id=self.region.sqid)
        assert response.status_code == 400

    def test_detail_has_bbox(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        bbox = data['data']['boundary']['bbox']
        assert bbox == list(self.region.boundary.geometry.extent)

    def test_detail_fields(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        assert set(data['data'].keys()) == {'id', 'name', 'slug', 'type', 'boundary', 'external_id', 'retired'}



def make_region(region_type, name, slug, geom_wkt):
    region = Region.objects.create(name=name, slug=slug, type=region_type)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_city(name, slug, geom_wkt):
    region = Region.objects.create(name=name, slug=slug, type=Region.Type.CITY)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_zip(code, geom_wkt):
    region = Region.objects.create(name=code, slug=f'zip-{code}', type=Region.Type.ZIPCODE, external_id=code)
    boundary = Boundary.objects.create(
        region=region, version='2020', geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_county(name, geom_wkt):
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.COUNTY)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_tract(name, geom_wkt):
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.TRACT)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


FRESNO_WKT = 'MULTIPOLYGON(((-119.9 36.7, -119.7 36.7, -119.7 36.9, -119.9 36.9, -119.9 36.7)))'
CLOVIS_CITY_WKT = 'MULTIPOLYGON(((-119.83 36.75, -119.73 36.75, -119.73 36.85, -119.83 36.85, -119.83 36.75)))'
FRESNO_COUNTY_WKT = 'MULTIPOLYGON(((-120.5 36.5, -119.0 36.5, -119.0 37.5, -120.5 37.5, -120.5 36.5)))'
KERN_COUNTY_WKT = 'MULTIPOLYGON(((-119.5 34.5, -118.0 34.5, -118.0 35.5, -119.5 35.5, -119.5 34.5)))'
FRESNO_TRACT_WKT = 'MULTIPOLYGON(((-120.2 36.8, -120.0 36.8, -120.0 37.0, -120.2 37.0, -120.2 36.8)))'
KERN_TRACT_WKT = 'MULTIPOLYGON(((-119.2 34.8, -119.0 34.8, -119.0 35.0, -119.2 35.0, -119.2 34.8)))'
ELSEWHERE_WKT = 'MULTIPOLYGON(((-116.0 33.0, -115.8 33.0, -115.8 33.2, -116.0 33.2, -116.0 33.0)))'


class TestPlaceSearch(TestCase):
    def setUp(self):
        self.fresno = make_region(Region.Type.URBAN_AREA, 'Fresno', 'fresno', FRESNO_WKT)
        self.clovis = make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        self.url = reverse('api:v2:regions:place-search')

    def test_returns_list(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        assert isinstance(response.json()['data'], list)

    def test_matches_by_name(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' in names

    def test_results_carry_code_and_retired(self):
        result = self.client.get(self.url, {'q': 'Fresno'}).json()['data'][0]
        assert 'external_id' in result and result['retired'] is None

    def test_case_insensitive(self):
        response = self.client.get(self.url, {'q': 'fresno'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' in names

    def test_type_filter_scopes_results(self):
        response = self.client.get(self.url, {'q': 'Clovis', 'type': 'city'})
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['name'] == 'Clovis'
        assert data[0]['type'] == 'city'

    def test_type_filter_excludes_other_types(self):
        response = self.client.get(self.url, {'q': 'Fresno', 'type': 'city'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' not in names

    def test_no_match_returns_empty_list(self):
        response = self.client.get(self.url, {'q': 'nonexistent'})
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_empty_query_returns_empty_list(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['data'] == []


class TestPlaceLookup(TestCase):
    def setUp(self):
        self.fresno = make_city('Fresno', 'fresno', FRESNO_WKT)
        self.url = reverse('api:v2:regions:place-lookup')

    def test_exact_match(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'
        assert response.json()['data']['type'] == Region.Type.CITY
        assert 'external_id' in response.json()['data']
        assert response.json()['data']['retired'] is None

    def test_case_insensitive(self):
        response = self.client.get(self.url, {'q': 'fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_fuzzy_match(self):
        response = self.client.get(self.url, {'q': 'Fresnoo'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_city_wins_over_urban_area_of_the_same_name(self):
        make_region(Region.Type.URBAN_AREA, 'Fresno', 'fresno-ua', FRESNO_WKT)
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.json()['data']['type'] == Region.Type.CITY

    def test_falls_back_to_cdp_then_urban_area(self):
        make_region(Region.Type.URBAN_AREA, 'Pixley', 'pixley-ua', ELSEWHERE_WKT)
        response = self.client.get(self.url, {'q': 'Pixley'})
        assert response.json()['data']['type'] == Region.Type.URBAN_AREA
        make_region(Region.Type.CDP, 'Pixley', 'pixley', ELSEWHERE_WKT)
        response = self.client.get(self.url, {'q': 'Pixley'})
        assert response.json()['data']['type'] == Region.Type.CDP

    def test_an_exact_name_beats_a_fuzzy_match_in_an_earlier_type(self):
        # "Riverbank" (a city) is a trigram hit for "Riverdale"; the CDP
        # carrying the exact name still wins.
        make_city('Riverbank', 'riverbank', CLOVIS_CITY_WKT)
        make_region(Region.Type.CDP, 'Riverdale', 'riverdale', ELSEWHERE_WKT)
        response = self.client.get(self.url, {'q': 'riverdale'})
        assert response.json()['data']['name'] == 'Riverdale'
        assert response.json()['data']['type'] == Region.Type.CDP

    def test_an_exact_name_prefers_the_city_over_the_cdp(self):
        make_region(Region.Type.CDP, 'Selma', 'selma-cdp', ELSEWHERE_WKT)
        make_city('Selma', 'selma', CLOVIS_CITY_WKT)
        response = self.client.get(self.url, {'q': 'Selma'})
        assert response.json()['data']['type'] == Region.Type.CITY

    def test_type_returns_direct_match(self):
        make_region(Region.Type.URBAN_AREA, 'Fresno', 'fresno-ua', FRESNO_WKT)
        response = self.client.get(self.url, {'q': 'Fresno', 'type': 'urban_area'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'
        assert response.json()['data']['type'] == 'urban_area'

    def test_no_match_returns_null(self):
        response = self.client.get(self.url, {'q': 'nonexistent'})
        assert response.status_code == 200
        assert response.json()['data'] is None

    def test_empty_query_returns_null(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['data'] is None

    def test_response_includes_boundary_geometry(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        boundary = response.json()['data']['boundary']
        assert boundary is not None
        assert boundary['geometry']['type'] == 'MultiPolygon'


class RegionGeoJSONTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:regions:region-geojson')

    def get(self, params):
        response = region_geojson(RequestFactory().get(self.url, params))
        return response, get_response_data(response)

    def test_route_is_not_read_as_a_region_id(self):
        assert self.url == '/api/2.0/regions/geojson/'

    def test_counties_as_a_feature_collection(self):
        response, data = self.get({'type': 'county'})
        assert response.status_code == 200
        assert data['type'] == 'FeatureCollection'
        counties = Region.objects.filter(type=Region.Type.COUNTY).exclude(boundary=None)
        assert len(data['features']) == counties.count() > 0
        feature = data['features'][0]
        assert feature['type'] == 'Feature'
        assert feature['id'] == feature['properties']['id']
        assert set(feature['properties']) == {'id', 'name', 'slug', 'type', 'external_id', 'retired'}
        assert feature['properties']['type'] == 'county'
        assert feature['geometry']['type'] == 'MultiPolygon'
        names = [f['properties']['name'] for f in data['features']]
        assert names == sorted(names)

    def test_coordinates_are_rounded(self):
        _, data = self.get({'type': 'county'})
        ring = data['features'][0]['geometry']['coordinates'][0][0]
        assert all(round(value, 5) == value for point in ring for value in point)

    def test_filters_are_the_region_lists(self):
        _, data = self.get({'type': 'county', 'slug': 'fresno'})
        assert [f['properties']['slug'] for f in data['features']] == ['fresno']

    def test_regions_without_a_boundary_are_left_out(self):
        Region.objects.create(name='Boundless County', slug='boundless', type=Region.Type.COUNTY)
        _, data = self.get({'type': 'county'})
        assert 'boundless' not in [f['properties']['slug'] for f in data['features']]

    def test_type_is_required(self):
        # Unfiltered, this would be every region in the database: thousands
        # of square-mile sections among them.
        response, data = self.get({})
        assert response.status_code == 400
        assert 'type' in str(data)

    def test_retired_tracts_are_left_out(self):
        current = make_tract('Tract 2020', FRESNO_TRACT_WKT)
        retired = make_tract('Tract 2010', KERN_TRACT_WKT)
        retired.boundary.version = '2010'
        retired.boundary.save(update_fields=['version'])
        _, data = self.get({'type': 'tract'})
        slugs = {f['properties']['slug'] for f in data['features']}
        assert current.slug in slugs and retired.slug not in slugs

    def test_simplified_shapes_share_their_borders(self):
        # Two tracts sharing the edge x = -120.1: simplified together, the
        # shared edge must come out identical on both sides (no gap, no
        # doubled line), and the result is lighter than the input.
        left = 'MULTIPOLYGON(((-120.2 36.8, -120.1 36.8, ' + ', '.join(
            f'-120.1 {36.8 + i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 37.0, -120.2 37.0, -120.2 36.8)))'
        right = 'MULTIPOLYGON(((-120.1 36.8, -120.0 36.8, -120.0 37.0, -120.1 37.0, ' + ', '.join(
            f'-120.1 {37.0 - i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 36.8)))'
        make_tract('Left', left)
        make_tract('Right', right)
        _, data = self.get({'type': 'tract', 'simplify': '1'})
        rings = {f['properties']['slug']: f['geometry']['coordinates'][0][0] for f in data['features']}
        on_edge = lambda ring: sorted({tuple(p) for p in ring if p[0] == -120.1})
        assert on_edge(rings['left']) == on_edge(rings['right'])
        assert len(rings['left']) < 100

    def test_simplified_keeps_the_filters(self):
        _, data = self.get({'type': 'county', 'slug': 'fresno', 'simplify': '1'})
        assert [f['properties']['slug'] for f in data['features']] == ['fresno']
        assert data['features'][0]['geometry']['type'] == 'MultiPolygon'

    def test_simplified_overlapping_shapes_fall_back_per_shape(self):
        # An invalid coverage (two tracts overlapping instead of sharing an
        # edge) must not blow up the whole request -- shapely.coverage_simplify
        # silently mangles topology on this input rather than raising, so the
        # coverage validity has to be checked before deciding which path to take.
        # A third, unrelated pair (left/right, sharing a clean edge elsewhere)
        # is included too: on real data, only a couple of shapes out of
        # hundreds are ever actually invalid, so the two overlapping tracts
        # must be simplified on their own while everyone else -- here, the
        # clean pair -- still goes through coverage_simplify together and
        # keeps an identical shared border.
        overlap_a = 'MULTIPOLYGON(((-120.2 36.8, -120.0 36.8, -120.0 37.0, -120.2 37.0, -120.2 36.8)))'
        overlap_b = 'MULTIPOLYGON(((-120.1 36.8, -119.9 36.8, -119.9 37.0, -120.1 37.0, -120.1 36.8)))'
        left = 'MULTIPOLYGON(((-120.2 38.8, -120.1 38.8, ' + ', '.join(
            f'-120.1 {38.8 + i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 39.0, -120.2 39.0, -120.2 38.8)))'
        right = 'MULTIPOLYGON(((-120.1 38.8, -120.0 38.8, -120.0 39.0, -120.1 39.0, ' + ', '.join(
            f'-120.1 {39.0 - i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 38.8)))'
        make_tract('Overlap A', overlap_a)
        make_tract('Overlap B', overlap_b)
        make_tract('Left', left)
        make_tract('Right', right)
        response, data = self.get({'type': 'tract', 'simplify': '1'})
        assert response.status_code == 200
        assert len(data['features']) == 4
        rings = {f['properties']['slug']: f['geometry']['coordinates'][0][0] for f in data['features']}
        on_edge = lambda ring: sorted({tuple(p) for p in ring if p[0] == -120.1})
        assert on_edge(rings['left']) == on_edge(rings['right'])

    def test_simplify_rejects_a_type_outside_the_areas_levels(self):
        # mtrs sections number in the tens of thousands; simplifying them on
        # demand for an anonymous request is the cost I2 flags. Only the
        # Areas levels (county, zipcode, tract) may use simplify=1.
        response, data = self.get({'type': 'mtrs', 'simplify': '1'})
        assert response.status_code == 400
        assert 'simplify' in str(data)

    def test_simplify_bypasses_the_response_cache(self):
        response, _ = self.get({'type': 'county', 'simplify': '1'})
        assert response['X-Cache-Status'] == 'MISS'
        response, _ = self.get({'type': 'county', 'simplify': '1'})
        assert response['X-Cache-Status'] != 'HIT'


class RegionWithinFilterTests(TestCase):
    def setUp(self):
        self.parent_a = make_county('Fresno County', FRESNO_COUNTY_WKT)
        self.parent_b = make_county('Kern County', KERN_COUNTY_WKT)
        self.inside_a = make_tract('Tract inside Fresno', FRESNO_TRACT_WKT)
        self.inside_b = make_tract('Tract inside Kern', KERN_TRACT_WKT)
        self.outside = make_tract('Tract elsewhere', ELSEWHERE_WKT)

    def _ids(self, *params):
        request = RequestFactory().get('/', list(params))
        response = region_list(request)
        assert response.status_code == 200
        data = get_response_data(response)
        return {r['id'] for r in data['data']}

    def test_within_single_parent_narrows_to_contained_regions(self):
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}

    def test_within_multiple_parents_unions_geometries(self):
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid), ('within', self.parent_b.sqid))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid}

    def test_within_unknown_id_returns_nothing(self):
        # Nothing can be inside a parent that doesn't exist. Falling back to
        # the unnarrowed list would hand back every region in the database.
        ids = self._ids(('type', 'tract'), ('within', 'not-a-real-sqid'))
        assert ids == set()

    def test_within_parent_without_boundary_returns_nothing(self):
        no_boundary = Region.objects.create(name='Boundless', slug='boundless', type=Region.Type.COUNTY)
        ids = self._ids(('type', 'tract'), ('within', no_boundary.sqid))
        assert ids == set()

    def test_within_blank_value_is_ignored(self):
        ids = self._ids(('type', 'tract'), ('within', ''))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid, self.outside.sqid}

    def test_no_within_param_returns_unnarrowed_list(self):
        ids = self._ids(('type', 'tract'))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid, self.outside.sqid}

    def test_within_excludes_a_region_that_only_touches_the_border(self):
        # Shares the exact edge (x=-119.0) with FRESNO_COUNTY_WKT's eastern
        # boundary but has zero interior overlap with it. ST_Intersects (plain
        # `.intersects()`) matches boundary-only touching, which `within=`
        # must not treat as "inside" the selected parent region.
        touching_neighbor = make_tract(
            'Tract touching Fresno border',
            'MULTIPOLYGON(((-119.0 36.8, -118.8 36.8, -118.8 37.0, -119.0 37.0, -119.0 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert touching_neighbor.sqid not in ids

    def test_within_excludes_a_neighbor_overlapping_by_a_sliver(self):
        # Real tract/ZIP boundaries come from different sources than county
        # boundaries and overlap neighbors by hairline slivers - genuine area,
        # so NOT ST_Touches doesn't help. This 0.2 x 0.2 tract pokes 0.0001
        # (0.05% of its area) across Fresno's eastern edge at x=-119.0; the
        # real-world case is a Kings/Madera/Tulare tract along the county line.
        sliver_neighbor = make_tract(
            'Tract overlapping Fresno by a sliver',
            'MULTIPOLYGON(((-119.0001 36.8, -118.8001 36.8, -118.8001 37.0, -119.0001 37.0, -119.0001 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert sliver_neighbor.sqid not in ids

    def test_within_excludes_a_region_that_only_partially_overlaps(self):
        # Straddles FRESNO_COUNTY_WKT's eastern boundary (x=-119.0) with
        # substantial area on both sides (roughly half inside, half outside)
        # - the real-world case is a congressional district crossing a
        # county line: it genuinely intersects Fresno County, but it is not
        # *within* it, so within= must exclude it too.
        straddling_district = make_tract(
            'District straddling Fresno border',
            'MULTIPOLYGON(((-119.3 36.8, -118.7 36.8, -118.7 37.0, -119.3 37.0, -119.3 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert straddling_district.sqid not in ids

    def test_within_includes_a_region_poking_a_sliver_outside(self):
        # The mirror of the sliver-neighbor case: a tract that is
        # unambiguously inside Fresno but whose boundary disagrees with the
        # county's by a hairline, poking 0.0001 (0.05% of its area) past the
        # county line at x=-119.0. Strict ST_Within would drop it; on real
        # data that loses ~15% of a county's tracts.
        sliver_out = make_tract(
            'Tract inside Fresno poking out',
            'MULTIPOLYGON(((-119.2 36.8, -118.9999 36.8, -118.9999 37.0, -119.2 37.0, -119.2 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid, sliver_out.sqid}


class RegionWithinOverlapsTests(TestCase):
    def setUp(self):
        self.fresno = make_county('Fresno County', FRESNO_COUNTY_WKT)
        self.kern = make_county('Kern County', KERN_COUNTY_WKT)
        # Straddles Fresno's eastern edge (x=-119.0), about half in Madera's
        # stand-in, which here is a county east of the line.
        self.madera = make_county(
            'Madera County',
            'MULTIPOLYGON(((-119.0 36.5, -117.5 36.5, -117.5 37.5, -119.0 37.5, -119.0 36.5)))',
        )
        self.inside = make_zip('93000', 'MULTIPOLYGON(((-120.2 36.8, -120.0 36.8, -120.0 37.0, -120.2 37.0, -120.2 36.8)))')
        self.straddler = make_zip('93001', 'MULTIPOLYGON(((-119.3 36.8, -118.7 36.8, -118.7 37.0, -119.3 37.0, -119.3 36.8)))')

    def _get(self, *params):
        response = region_list(RequestFactory().get('/', list(params)))
        return response, get_response_data(response)

    def _overlaps(self, parent):
        return self._get(('type', 'zipcode'), ('within', parent.sqid), ('within_mode', 'overlaps'))

    def test_within_default_unchanged(self):
        response, data = self._get(('type', 'zipcode'), ('within', self.fresno.sqid))
        assert {r['id'] for r in data['data']} == {self.inside.sqid}
        assert 'also_in' not in data['data'][0]

    def test_overlaps_includes_straddler_with_also_in(self):
        response, data = self._overlaps(self.fresno)
        rows = {r['id']: r for r in data['data']}
        assert set(rows) == {self.inside.sqid, self.straddler.sqid}
        assert rows[self.inside.sqid]['also_in'] == []
        assert rows[self.straddler.sqid]['also_in'] == [
            {'type': 'county', 'external_id': self.madera.external_id, 'name': 'Madera County'},
        ]

    def test_bad_within_mode_400(self):
        response, data = self._get(('type', 'zipcode'), ('within', self.fresno.sqid), ('within_mode', 'bogus'))
        assert response.status_code == 400
        assert data['error'] == 'within_mode must be contained or overlaps.'

    def test_also_in_drops_a_sliver_under_one_percent(self):
        # Reaches 0.0005 deg into the straddler's top edge: 0.25% of its area.
        make_county('Sliver County', 'MULTIPOLYGON(((-119.3 36.9995, -118.7 36.9995, -118.7 37.5, -119.3 37.5, -119.3 36.9995)))')
        response, data = self._overlaps(self.fresno)
        rows = {r['id']: r for r in data['data']}
        assert [c['name'] for c in rows[self.straddler.sqid]['also_in']] == ['Madera County']

    def test_also_in_leaves_out_every_within_parent(self):
        # A third county holding 25% of the straddler: it alone stays in also_in.
        tulare = make_county('Tulare County', 'MULTIPOLYGON(((-119.3 36.95, -118.7 36.95, -118.7 37.5, -119.3 37.5, -119.3 36.95)))')
        response, data = self._get(
            ('type', 'zipcode'), ('within', self.fresno.sqid), ('within', self.madera.sqid),
            ('within_mode', 'overlaps'))
        rows = {r['id']: r for r in data['data']}
        assert rows[self.straddler.sqid]['also_in'] == [
            {'type': 'county', 'external_id': tulare.external_id, 'name': 'Tulare County'},
        ]
        assert rows[self.inside.sqid]['also_in'] == []

    def test_also_in_skips_a_retired_candidate(self):
        self.madera.retire(date(2026, 10, 1))
        response, data = self._overlaps(self.fresno)
        rows = {r['id']: r for r in data['data']}
        assert rows[self.straddler.sqid]['also_in'] == []

    def test_bad_within_mode_400_on_geojson(self):
        request = RequestFactory().get('/', [('type', 'zipcode'), ('within', self.fresno.sqid), ('within_mode', 'bogus')])
        response = region_geojson(request)
        assert response.status_code == 400
        assert get_response_data(response)['error'] == 'within_mode must be contained or overlaps.'

    def test_overlaps_applies_to_geojson(self):
        request = RequestFactory().get('/', [('type', 'zipcode'), ('within', self.fresno.sqid), ('within_mode', 'overlaps')])
        data = get_response_data(region_geojson(request))
        assert {f['id'] for f in data['features']} == {self.inside.sqid, self.straddler.sqid}

    def test_overlaps_query_count(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response, data = self._overlaps(self.fresno)
            return len(ctx), len(data['data'])

        few_queries, few = count_queries()
        for i in range(4):
            x = -120.4 + i * 0.05
            make_zip(f'9310{i}', f'MULTIPOLYGON((({x} 36.6, {x + 0.04} 36.6, {x + 0.04} 36.7, {x} 36.7, {x} 36.6)))')
        many_queries, many = count_queries()
        assert (few, many) == (2, 6)
        assert few_queries == many_queries


class RetiredRegionTests(TestCase):
    """Listings and searches skip a retired region; naming it by sqid still finds it."""
    fixtures = ['regions.yaml']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.factory = RequestFactory()
        self.region = Region.objects.get(name='Fresno County')
        self.region.retire(date(2026, 10, 1))

    def test_detail_by_sqid_finds_retired_region(self):
        response = region_detail(self.factory.get('/'), region_id=self.region.sqid)
        assert response.status_code == 200
        assert get_response_data(response)['data']['id'] == self.region.sqid

    def test_list_and_search_skip_retired(self):
        response = region_list(self.factory.get('/', {'type': self.region.type}))
        ids = [r['id'] for r in get_response_data(response)['data']]
        assert ids
        assert self.region.sqid not in ids
        assert self.region not in Region.objects.search_regions(self.region.name, type=self.region.type)

    def test_unfiltered_list_skips_retired(self):
        ids = [r['id'] for r in get_response_data(region_list(self.factory.get('/')))['data']]
        assert self.region.sqid not in ids

    def test_geojson_skips_retired(self):
        response = region_geojson(self.factory.get('/', {'type': self.region.type}))
        ids = [f['id'] for f in get_response_data(response)['features']]
        assert ids
        assert self.region.sqid not in ids

    def test_within_accepts_a_retired_parent(self):
        tract = make_tract('Tract inside Fresno', FRESNO_TRACT_WKT)
        parent = make_county('Old Fresno County', FRESNO_COUNTY_WKT)
        parent.retire(date(2026, 10, 1))
        response = region_list(self.factory.get('/', [('type', 'tract'), ('within', parent.sqid)]))
        ids = {r['id'] for r in get_response_data(response)['data']}
        assert tract.sqid in ids

    def test_place_lookup_skips_retired(self):
        assert Region.objects.resolve_place(self.region.name, type=self.region.type) != self.region


class RegionCodeLookupTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.factory = RequestFactory()

    def get(self, params):
        response = region_list(self.factory.get('/', params))
        return response, get_response_data(response)

    def test_lookup_by_several_codes(self):
        counties = list(Region.objects.filter(type='county')[:2])
        codes = ','.join(c.external_id for c in counties)
        _, data = self.get({'type': 'county', 'external_id': codes})
        assert {r['external_id'] for r in data['data']} == {c.external_id for c in counties}

    def test_lookup_cleans_the_list(self):
        c = Region.objects.filter(type='county').first()
        _, data = self.get({'type': 'county', 'external_id': f' {c.external_id}, ,{c.external_id}'})
        assert [r['external_id'] for r in data['data']] == [c.external_id]

    def test_lookup_returns_retired_flagged_and_skips_unknown(self):
        c = Region.objects.filter(type='county').first()
        c.retire(date(2026, 10, 1))
        _, data = self.get({'type': 'county', 'external_id': f'{c.external_id},99999'})
        assert len(data['data']) == 1
        assert data['data'][0]['retired'] == {'since': '2026-10-01', 'replaced_by': None}

    def test_lookup_names_the_replacement_by_code(self):
        old, new = list(Region.objects.filter(type='county')[:2])
        old.retire(date(2026, 10, 1), replaced_by=new)
        _, data = self.get({'type': 'county', 'external_id': old.external_id})
        assert data['data'][0]['retired']['replaced_by'] == {'type': 'county', 'external_id': new.external_id}

    def test_current_region_is_not_flagged(self):
        c = Region.objects.filter(type='county').first()
        _, data = self.get({'type': 'county', 'external_id': c.external_id})
        assert data['data'][0]['retired'] is None

    def test_lookup_only_matches_the_given_type(self):
        c = Region.objects.filter(type='county').first()
        _, data = self.get({'type': 'zipcode', 'external_id': c.external_id})
        assert data['data'] == []

    def test_lookup_requires_type(self):
        response, data = self.get({'external_id': '06019'})
        assert response.status_code == 400
        assert data['error'] == 'The type parameter is required with external_id.'

    def test_lookup_refuses_land_use(self):
        response, data = self.get({'type': 'land_use', 'external_id': '1'})
        assert response.status_code == 400
        assert data['error'] == "Land-use regions can't be looked up by code yet."

    def test_docs_say_land_use_codes_are_not_permanent(self):
        from camp.api.v2.regions.filters import RegionFilter
        from camp.api.v2.regions.serializers import RegionSerializer
        help_text = RegionFilter.base_filters['external_id'].extra['help_text']
        assert 'land_use' in help_text and 'not a permanent code' in help_text
        assert 'NOT a permanent code' in ' '.join(RegionSerializer.__doc__.split())

    def test_lookup_caps_codes(self):
        codes = ','.join(str(n) for n in range(101))
        response, _ = self.get({'type': 'county', 'external_id': codes})
        assert response.status_code == 400
        codes = ','.join(str(n) for n in range(100))
        response, _ = self.get({'type': 'county', 'external_id': codes})
        assert response.status_code == 200

    def test_geojson_properties_include_code(self):
        c = Region.objects.filter(type='county').exclude(boundary=None).first()
        response = region_geojson(self.factory.get('/', {'type': 'county'}))
        props = {f['id']: f['properties'] for f in get_response_data(response)['features']}[c.sqid]
        assert props['external_id'] == c.external_id
        assert props['retired'] is None

    def test_simplified_geojson_properties_include_code(self):
        response = region_geojson(self.factory.get('/', {'type': 'county', 'simplify': '1'}))
        props = get_response_data(response)['features'][0]['properties']
        assert 'external_id' in props and 'retired' in props


class LocationLookupTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        from django.core.cache import cache
        from django.contrib.gis.geos import Point
        cache.clear()
        self.factory = RequestFactory()
        self.county = Region.objects.filter(type='county').first()
        self.school = Location.all_objects.create(
            type=Location.Type.PUBLIC_SCHOOL, source='cde-public', external_id='15634380000001',
            name='Test Elementary', address='1 Main St', city_name='Bakersfield', zip='93301',
            point=Point(-119.0, 35.4, srid=4326), county=self.county)
        self.child_care = Location.all_objects.create(
            type=Location.Type.CHILD_CARE, source='cdss-ccl', external_id='153400001',
            name='Little Ones', point=Point(-119.1, 35.5, srid=4326),
            metadata={'facility_numbers': ['153400001', '153400002']})

    def get(self, params):
        response = location_list(self.factory.get('/', params))
        return response, get_response_data(response)

    def test_lookup_by_code(self):
        response, data = self.get({'source': 'cde-public', 'external_id': self.school.external_id})
        assert response.status_code == 200
        (item,) = data['data']
        assert item['id'] == self.school.sqid
        assert item['source'] == 'cde-public'
        assert item['external_id'] == '15634380000001'
        assert item['aliases'] == []
        assert item['type'] == 'public_school'
        assert item['name'] == 'Test Elementary'
        assert item['city_name'] == 'Bakersfield'
        assert item['zip'] == '93301'
        assert item['point'] == {'lat': 35.4, 'lng': -119.0}
        assert item['regions']['county'] == {'type': 'county', 'external_id': self.county.external_id}
        assert item['regions']['city'] is None
        assert item['retired'] is None

    def test_lookup_by_non_key_license_number(self):
        _, data = self.get({'source': 'cdss-ccl', 'external_id': '153400002'})
        (item,) = data['data']
        assert item['external_id'] == '153400001'
        assert item['aliases'] == ['153400002']

    def test_two_codes_for_one_site_return_it_once(self):
        _, data = self.get({'source': 'cdss-ccl', 'external_id': '153400001,153400002'})
        assert len(data['data']) == 1

    def test_retired_is_returned_flagged(self):
        self.school.retire(date(2026, 10, 1))
        _, data = self.get({'source': 'cde-public', 'external_id': self.school.external_id})
        assert data['data'][0]['retired'] == {'since': '2026-10-01', 'replaced_by': None}

    def test_unknown_code_is_absent(self):
        _, data = self.get({'source': 'cde-public', 'external_id': '000'})
        assert data['data'] == []

    def test_source_scopes_the_lookup(self):
        _, data = self.get({'source': 'cde-private', 'external_id': self.school.external_id})
        assert data['data'] == []

    def test_missing_params_are_400(self):
        assert self.get({'external_id': '1'})[0].status_code == 400
        assert self.get({'source': 'cde-public'})[0].status_code == 400
        assert self.get({})[0].status_code == 400

    def test_unknown_source_is_400(self):
        assert self.get({'source': 'nope', 'external_id': '1'})[0].status_code == 400

    def test_caps_codes(self):
        codes = ','.join(str(n) for n in range(101))
        assert self.get({'source': 'cde-public', 'external_id': codes})[0].status_code == 400
        codes = ','.join(str(n) for n in range(100))
        assert self.get({'source': 'cde-public', 'external_id': codes})[0].status_code == 200

    def test_url_is_not_swallowed_by_region_id(self):
        response = self.client.get(reverse('api:v2:regions:location-list'),
            {'source': 'cde-public', 'external_id': self.school.external_id})
        assert response.status_code == 200


class PlaceLookupPointTests(TestCase):
    """POST regions/places/lookup/ with coordinates, and GET ?monitor=."""

    def setUp(self):
        cache.clear()
        self.url = reverse('api:v2:regions:place-lookup')
        self.county = make_square_region('Test County', Region.Type.COUNTY, '99001', (-121, 35, -117, 38))
        self.city = make_square_region('Test City', Region.Type.CITY, '99002', (-119.8, 36.2, -119.2, 36.8))
        self.zip_a = make_square_region('99100', Region.Type.ZIPCODE, '99100', (-120, 36, -119, 37))
        self.zip_b = make_square_region('99200', Region.Type.ZIPCODE, '99200', (-119, 36, -118, 37))

    def post(self, payload, client=None):
        return (client or self.client).post(
            self.url, json.dumps(payload), content_type='application/json')

    def ids(self, response):
        assert response.status_code == 200
        return [(r['type'], r['external_id']) for r in response.json()['data']]

    def test_point_returns_containing_regions_sorted(self):
        response = self.post({'lat': 36.5, 'lon': -119.5})
        assert self.ids(response) == [('city', '99002'), ('county', '99001'), ('zipcode', '99100')]
        assert set(response.json()['data'][0]['boundary']) == {'id', 'version', 'bbox'}

    def test_point_rounded_before_lookup(self):
        with patch('camp.api.v2.regions.endpoints.regions_containing', wraps=regions_containing) as spy:
            first = self.post({'lat': 36.73749, 'lon': -119.5})
            second = self.post({'lat': 36.7371, 'lon': -119.5})
        keys = {call.args[2] for call in spy.call_args_list}
        assert len(keys) == 1
        assert round_point(36.73749, -119.5) == round_point(36.7371, -119.5) == (36.737, -119.5)
        assert first.json() == second.json()

    def test_type_list_filters(self):
        assert self.ids(self.post({'lat': 36.5, 'lon': -119.5, 'type': 'county, zipcode'})) == [
            ('county', '99001'), ('zipcode', '99100')]
        # Order and repeats in the list don't matter.
        assert self.ids(self.post({'lat': 36.5, 'lon': -119.5, 'type': 'zipcode,county,county'})) == [
            ('county', '99001'), ('zipcode', '99100')]

    def test_default_excludes_land_use_and_mtrs(self):
        make_square_region('Land', Region.Type.LAND_USE, '1', (-120, 36, -119, 37))
        make_square_region('Section', Region.Type.MTRS, 'M1', (-120, 36, -119, 37))
        types = {t for t, _ in self.ids(self.post({'lat': 36.5, 'lon': -119.5}))}
        assert types == {'city', 'county', 'zipcode'}

    def test_explicit_land_use_400(self):
        response = self.post({'lat': 36.5, 'lon': -119.5, 'type': 'land_use'})
        assert response.status_code == 400
        assert response.json()['error'] == "Land-use regions can't be looked up."

    def test_unknown_type_400(self):
        response = self.post({'lat': 36.5, 'lon': -119.5, 'type': 'nope'})
        assert response.status_code == 400
        assert response.json()['error'] == 'Unknown region type: nope.'

    def test_type_json_list_filters(self):
        assert self.ids(self.post({'lat': 36.5, 'lon': -119.5, 'type': ['zipcode', 'county']})) == [
            ('county', '99001'), ('zipcode', '99100')]

    def test_type_null_means_default(self):
        types = {t for t, _ in self.ids(self.post({'lat': 36.5, 'lon': -119.5, 'type': None}))}
        assert types == {'city', 'county', 'zipcode'}

    def test_type_json_list_unknown_type_400(self):
        response = self.post({'lat': 36.5, 'lon': -119.5, 'type': ['county', 'nope']})
        assert response.status_code == 400
        assert response.json()['error'] == 'Unknown region type: nope.'

    def test_type_of_another_kind_400(self):
        for value in (5, {'county': True}, ['county', 5], [['county']]):
            response = self.post({'lat': 36.5, 'lon': -119.5, 'type': value})
            assert response.status_code == 400, value
            assert response.json()['error'] == 'type must be a comma-separated string or a list of strings.'

    def test_coordinates_hidden_from_django_error_reports(self):
        # Django's error emails and debug page read frame locals through this filter.
        # Resticus turns the exception into a 500, so grab the live stack from
        # inside the lookup instead of from a traceback.
        import inspect
        from django.views.debug import SafeExceptionReporterFilter
        report_filter = SafeExceptionReporterFilter()
        seen = {}

        def capture(*args):
            frame = inspect.currentframe().f_back
            while frame is not None:
                seen[frame] = dict(report_filter.get_traceback_frame_variables(None, frame))
                frame = frame.f_back
            return []

        with patch('camp.api.v2.regions.endpoints.regions_containing', side_effect=capture):
            assert self.post({'lat': 36.737, 'lon': -119.787}).status_code == 200
        endpoint_frames = {f: v for f, v in seen.items() if f.f_code.co_filename.endswith('regions/endpoints.py')}
        assert any(f.f_code.co_name == 'post' and 'lat' in f.f_locals for f in endpoint_frames)
        for frame, variables in endpoint_frames.items():
            for name in ('body', 'form', 'lat', 'lon', 'geometry'):
                if name in variables:
                    assert variables[name] == report_filter.cleansed_substitute, (frame.f_code.co_name, name)
        seen.clear()
        endpoint_frames.clear()

    def test_mtrs_allowed_when_asked(self):
        make_square_region('Section', Region.Type.MTRS, 'M1', (-120, 36, -119, 37))
        assert self.ids(self.post({'lat': 36.5, 'lon': -119.5, 'type': 'mtrs'})) == [('mtrs', 'M1')]

    def test_point_outside_everything_empty_list(self):
        response = self.post({'lat': 10, 'lon': 10})
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_point_on_shared_edge_returns_both(self):
        found = self.ids(self.post({'lat': 36.5, 'lon': -119, 'type': 'zipcode'}))
        assert found == [('zipcode', '99100'), ('zipcode', '99200')]

    def test_retired_region_excluded(self):
        self.zip_a.retired_at = timezone.now()
        self.zip_a.save()
        assert ('zipcode', '99100') not in self.ids(self.post({'lat': 36.5, 'lon': -119.5}))

    def test_bad_coordinates_400_without_echo(self):
        cases = [
            {'lat': 'abc', 'lon': -119.5},
            {'lat': 'NaN', 'lon': -119.5},
            {'lat': 91, 'lon': -119.5},
            {'lat': 36.5, 'lon': -181},
            {'lat': 36.5, 'lon': 'zzz-7'},
            {'lat': 36.5},
        ]
        for payload in cases:
            response = self.post(payload)
            assert response.status_code == 400, payload
            for echoed in ('abc', 'NaN', '91', '-181', 'zzz-7'):
                assert echoed not in response.content.decode(), payload

    def test_nonfinite_json_literal_400(self):
        response = self.client.post(
            self.url, '{"lat": NaN, "lon": -119.5}', content_type='application/json')
        assert response.status_code == 400

    def test_coordinates_in_query_string_400(self):
        response = self.client.get(self.url, {'lat': '36.5', 'lon': '-119.5'})
        assert response.status_code == 400
        assert response.json()['error'] == 'Send coordinates in a POST body.'
        assert '36.5' not in response.content.decode()

    def test_post_with_q_400(self):
        assert self.post({'q': 'Fresno', 'lat': 36.5, 'lon': -119.5}).status_code == 400

    def test_monitor_mode(self):
        monitor = AirNow.objects.create(
            name='M', position=Point(-119.5, 36.5, srid=4326),
            location='outside')
        response = self.client.get(self.url, {'monitor': str(monitor.pk), 'type': 'county,zipcode'})
        assert self.ids(response) == [('county', '99001'), ('zipcode', '99100')]

    def test_hidden_monitor_404(self):
        monitor = AirNow.objects.create(
            name='M', position=Point(-119.5, 36.5, srid=4326),
            location='outside', is_hidden=True)
        assert self.client.get(self.url, {'monitor': str(monitor.pk)}).status_code == 404

    def test_monitor_without_position_400(self):
        monitor = AirNow.objects.create(
            name='No Pos', position=None, location='outside')
        response = self.client.get(self.url, {'monitor': str(monitor.pk)})
        assert response.status_code == 400
        assert response.json()['error'] == 'Monitor has no location.'

    def test_cimis_monitor_resolves(self):
        monitor = CIMIS.objects.create(
            name='Weather', station_number='6', position=Point(-119.5, 36.5, srid=4326),
            location=CIMIS.LOCATION.outside)
        response = self.client.get(self.url, {'monitor': str(monitor.pk), 'type': 'county'})
        assert self.ids(response) == [('county', '99001')]

    def test_monitor_land_use_400(self):
        monitor = AirNow.objects.create(
            name='M', position=Point(-119.5, 36.5, srid=4326), location='outside')
        assert self.client.get(
            self.url, {'monitor': str(monitor.pk), 'type': 'land_use'}).status_code == 400

    def test_cache_keys_are_memcached_safe(self):
        from camp.apps.regions.resolve import monitor_lookup_key, point_lookup_key
        types = tuple(sorted(Region.Type.values))
        monitor = AirNow.objects.create(
            name='M', position=Point(-119.5, 36.5, srid=4326), location='outside')
        for key in (point_lookup_key(36.5, -119.5, types), monitor_lookup_key(monitor, types)):
            assert list(memcache_key_warnings(cache.make_key(key))) == [], key

    def test_monitor_with_q_400(self):
        assert self.client.get(self.url, {'monitor': 'abc', 'q': 'Fresno'}).status_code == 400

    def test_name_mode_unchanged(self):
        response = self.client.get(self.url, {'q': 'Test City', 'type': 'city'})
        assert response.status_code == 200
        assert response.json()['data']['external_id'] == '99002'
        assert self.client.get(self.url, {'q': 'Zzzzzz Qqqq'}).json()['data'] is None

    def test_anonymous_post_without_csrf_token_200(self):
        client = Client(enforce_csrf_checks=True)
        assert self.post({'lat': 36.5, 'lon': -119.5}, client=client).status_code == 200

    def test_signed_in_post_without_csrf_token_403(self):
        try:
            from resticus.auth import enforce_csrf  # noqa: F401
        except ImportError:
            pytest.skip('resticus without the session CSRF fix')
        user = User.objects.create_user(
            'lookup@sjvair.com', 'letmein1', full_name='Look Up', phone='+15595550001')
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        assert self.post({'lat': 36.5, 'lon': -119.5}, client=client).status_code == 403

    def test_warm_lookup_no_queries(self):
        payload = {'lat': 36.5, 'lon': -119.5}
        self.post(payload)
        with self.assertNumQueries(0):
            response = self.post(payload)
        assert response.status_code == 200
        assert len(response.json()['data']) == 3

    def test_empty_result_is_cached(self):
        payload = {'lat': 10, 'lon': 10}
        self.post(payload)
        with self.assertNumQueries(0):
            assert self.post(payload).json()['data'] == []
