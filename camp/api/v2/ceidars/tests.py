import pytest

from django.contrib.gis.geos import Point, MultiPolygon, Polygon
from django.urls import reverse

from camp.apps.ceidars.models import EmissionsRecord, Facility
from camp.apps.regions.models import Boundary, Region


@pytest.fixture
def facility(db):
    return Facility.objects.create(
        county_code=10,
        facid=1,
        name='TEST PLANT',
        address={'street': '123 MAIN ST', 'city': 'FRESNO', 'zipcode': '93701'},
        point=Point(-119.787, 36.737, srid=4326),
    )


@pytest.fixture
def record(facility):
    return EmissionsRecord.objects.create(
        facility=facility,
        year=2023,
        pm25='1.5',
        pm10='2.0',
        nox='3.0',
    )


@pytest.fixture
def fresno_region(db):
    region = Region.objects.create(
        name='Fresno',
        slug='fresno',
        type=Region.Type.COUNTY,
    )
    poly = Polygon.from_bbox((-120.5, 36.0, -119.0, 37.5))
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=MultiPolygon(poly),
    )
    region.boundary = boundary
    region.save()
    return region


class TestCeidarsEndpoint:
    def test_returns_facilities_for_latest_year(self, client, record):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['name'] == 'TEST PLANT'
        assert data[0]['year'] == 2023
        assert data[0]['pm25'] is not None

    def test_returns_facilities_for_specific_year(self, client, record):
        url = reverse('api:v2:ceidars:list-by-year', kwargs={'year': 2023})
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1

    def test_excludes_facilities_without_position(self, client, db):
        facility = Facility.objects.create(
            county_code=10, facid=99, name='NO POSITION',
            address={'city': 'FRESNO', 'zipcode': '93701'},
        )
        EmissionsRecord.objects.create(facility=facility, year=2023)
        url = reverse('api:v2:ceidars:list')
        response = client.get(url)
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'NO POSITION' not in names

    def test_excludes_facilities_without_record_for_year(self, client, facility):
        # facility exists but has no EmissionsRecord
        url = reverse('api:v2:ceidars:list')
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_bbox_filter(self, client, record):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'bbox': '-120.0,36.0,-119.0,37.5'})
        assert response.status_code == 200
        assert len(response.json()['data']) == 1

    def test_bbox_filter_excludes_outside(self, client, record):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'bbox': '0,0,1,1'})
        assert response.status_code == 200
        assert len(response.json()['data']) == 0

    def test_region_filter(self, client, record, fresno_region):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'region': 'fresno', 'region_type': 'county'})
        assert response.status_code == 200
        assert len(response.json()['data']) == 1

    def test_region_not_found_returns_404(self, client, record):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'region': 'nonexistent'})
        assert response.status_code == 404

    def test_bbox_and_region_returns_400(self, client, record):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'bbox': '-120,36,-119,37', 'region': 'fresno'})
        assert response.status_code == 400

    def test_empty_when_no_records(self, client, db):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_ambiguous_region_slug_returns_400(self, client, record):
        # Two regions share the same slug but different types — no region_type → 400
        Region.objects.create(name='Central', slug='central', type=Region.Type.COUNTY)
        Region.objects.create(name='Central', slug='central', type=Region.Type.CITY)
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'region': 'central'})
        assert response.status_code == 400

    def test_region_without_boundary_returns_empty_list(self, client, record):
        # Region exists but has no boundary set
        Region.objects.create(name='Kern', slug='kern', type=Region.Type.COUNTY)
        url = reverse('api:v2:ceidars:list')
        response = client.get(url, {'region': 'kern', 'region_type': 'county'})
        assert response.status_code == 200
        assert response.json()['data'] == []
