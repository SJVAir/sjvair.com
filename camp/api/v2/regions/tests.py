import pytest

from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.regions.endpoints import RegionDetail, RegionList
from camp.apps.regions.models import Boundary, Region
from camp.utils.test import get_response_data

region_list = RegionList.as_view()
region_detail = RegionDetail.as_view()

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


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
        assert set(data['data'][0].keys()) == {'id', 'name', 'slug', 'type', 'boundary'}

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


class RegionDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def test_detail_returns_200(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        assert response.status_code == 200

    def test_detail_has_geometry(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        data = get_response_data(response)
        assert data['data']['boundary'] is not None
        assert data['data']['boundary']['geometry'] is not None

    def test_detail_fields(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        data = get_response_data(response)
        assert set(data['data'].keys()) == {'id', 'name', 'slug', 'type', 'boundary'}



def make_place(name, slug, geom_wkt):
    region = Region.objects.create(name=name, slug=slug, type=Region.Type.PLACE)
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


FRESNO_PLACE_WKT = 'MULTIPOLYGON(((-119.9 36.7, -119.7 36.7, -119.7 36.9, -119.9 36.9, -119.9 36.7)))'
CLOVIS_CITY_WKT = 'MULTIPOLYGON(((-119.83 36.75, -119.73 36.75, -119.73 36.85, -119.83 36.85, -119.83 36.75)))'


class TestPlaceSearch(TestCase):
    def setUp(self):
        self.fresno = make_place('Fresno', 'fresno', FRESNO_PLACE_WKT)
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
        self.fresno = make_place('Fresno', 'fresno', FRESNO_PLACE_WKT)
        self.url = reverse('api:v2:regions:place-lookup')

    def test_exact_match(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'
        assert response.json()['data']['type'] == Region.Type.PLACE

    def test_case_insensitive(self):
        response = self.client.get(self.url, {'q': 'fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_fuzzy_match(self):
        response = self.client.get(self.url, {'q': 'Fresnoo'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_city_resolves_to_containing_place(self):
        make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        response = self.client.get(self.url, {'q': 'Clovis'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_type_returns_direct_match_not_place(self):
        make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        response = self.client.get(self.url, {'q': 'Clovis', 'type': 'city'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Clovis'
        assert response.json()['data']['type'] == 'city'

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
