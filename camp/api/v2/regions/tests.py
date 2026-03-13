import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.regions.endpoints import RegionDetail, RegionList
from camp.apps.regions.models import Region
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

    def test_list_has_no_geometry(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert 'geometry' not in data['data'][0]

    def test_list_fields(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert set(data['data'][0].keys()) == {'id', 'name', 'type'}

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
        assert 'geometry' in data['data']
        assert data['data']['geometry'] is not None

    def test_detail_fields(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        data = get_response_data(response)
        assert set(data['data'].keys()) == {'id', 'name', 'type', 'geometry'}

    def test_detail_null_geometry_for_region_without_boundary(self):
        region = Region.objects.filter(boundary__isnull=True).first()
        if region is None:
            return  # skip: all fixtures have boundaries
        request = self.factory.get('/')
        response = region_detail(request, region_id=region.pk)
        data = get_response_data(response)
        assert data['data']['geometry'] is None
