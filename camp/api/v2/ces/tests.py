from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.ces import endpoints
from camp.apps.regions.models import Boundary, Region
from camp.utils.test import get_response_data

ces4_list = endpoints.CES4List.as_view()
ces4_detail = endpoints.CES4Detail.as_view()


class CES4EndpointTests(TestCase):
    fixtures = ['calenviroscreen']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_2020_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url, {'year': '2020'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_2010_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url, {'year': '2010'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_defaults_to_2020_when_year_omitted(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url)
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2
        assert all(r['census_year'] == '2020' for r in data['data'])

    def test_list_records_have_expected_fields(self):
        request = self.factory.get('/')
        response = ces4_list(request)
        data = get_response_data(response)

        record = data['data'][0]
        assert 'id' in record
        assert 'tract' in record
        assert 'census_year' in record
        assert 'ci_score' in record
        assert 'ci_score_p' in record
        assert 'dac_sb535' in record
        assert 'pollution_p' in record
        assert 'popchar_p' in record

    def test_list_census_year_matches_requested_year(self):
        request = self.factory.get('/')
        response = ces4_list(request)
        data = get_response_data(response)

        assert all(r['census_year'] == '2020' for r in data['data'])

    def test_detail_returns_correct_tract(self):
        tract = '06019000101'
        request = self.factory.get('/')
        response = ces4_detail(request, tract=tract)
        data = get_response_data(response)

        assert response.status_code == 200
        assert data['data']['tract'] == tract
        assert data['data']['census_year'] == '2020'

    def test_detail_404_for_unknown_tract(self):
        request = self.factory.get('/')
        response = ces4_detail(request, tract='99999999999')

        assert response.status_code == 404

    def test_detail_404_for_wrong_year(self):
        # tract exists for 2020 but requesting 2030
        request = self.factory.get('/', {'year': '2030'})
        response = ces4_detail(request, tract='06019000101')

        assert response.status_code == 404

    def test_filter_by_dac_sb535(self):
        request = self.factory.get('/', {'dac_sb535': 'true'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 1
        assert data['data'][0]['dac_sb535'] is True

    def test_filter_by_ci_score_p_gte(self):
        request = self.factory.get('/', {'ci_score_p__gte': '80'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert all(r['ci_score_p'] >= 80 for r in data['data'])


class CES4RegionFilterTests(TestCase):
    # Fixture tracts (2020 boundaries):
    #   Tract 1.01: lon -119.8 to -119.7, lat 36.7 to 36.8
    #   Tract 1.02: lon -119.7 to -119.6, lat 36.7 to 36.8
    fixtures = ['calenviroscreen']

    COVERS_BOTH = 'MULTIPOLYGON (((-119.9 36.6, -119.5 36.6, -119.5 36.9, -119.9 36.9, -119.9 36.6)))'
    COVERS_ONLY_1_01 = 'MULTIPOLYGON (((-119.9 36.6, -119.71 36.6, -119.71 36.9, -119.9 36.9, -119.9 36.6)))'
    COVERS_NEITHER = 'MULTIPOLYGON (((-120.5 38.0, -120.4 38.0, -120.4 38.1, -120.5 38.1, -120.5 38.0)))'

    def _create_region(self, geometry_wkt=None):
        region = Region.objects.create(
            name='Test City', slug='test-city', type=Region.Type.CITY, external_id='9999',
        )
        if geometry_wkt:
            boundary = Boundary.objects.create(
                region=region, version='2020',
                geometry=GEOSGeometry(geometry_wkt, srid=4326),
            )
            region.boundary = boundary
            region.save()
        return region

    def test_region_covering_both_tracts_returns_two(self):
        region = self._create_region(self.COVERS_BOTH)
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': region.sqid, 'year': '2020'}).json()
        assert data['count'] == 2

    def test_region_covering_one_tract_returns_one(self):
        region = self._create_region(self.COVERS_ONLY_1_01)
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': region.sqid, 'year': '2020'}).json()
        assert data['count'] == 1
        assert data['data'][0]['tract'] == '06019000101'

    def test_region_outside_tracts_returns_empty(self):
        region = self._create_region(self.COVERS_NEITHER)
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': region.sqid, 'year': '2020'}).json()
        assert data['count'] == 0

    def test_region_without_boundary_returns_empty(self):
        region = self._create_region()
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': region.sqid, 'year': '2020'}).json()
        assert data['count'] == 0

    def test_invalid_region_id_returns_empty(self):
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': 'BOGUS', 'year': '2020'}).json()
        assert data['count'] == 0
