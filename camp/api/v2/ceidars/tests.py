import pytest

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from camp.apps.ceidars.models import EmissionsRecord, Facility


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


class TestCeidarsFilters(TestCase):
    fixtures = ['regions.yaml', 'ceidars.yaml']

    def test_sources_major(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url, {'sources': 'major'})
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST PLANT' in names
        assert 'TEST GAS STATION' not in names

    def test_sources_minor(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url, {'sources': 'minor'})
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST GAS STATION' in names
        assert 'TEST PLANT' not in names

    def test_sources_unfiltered_returns_all(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url)
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST PLANT' in names
        assert 'TEST GAS STATION' in names

    def test_county_filter(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url, {'county': 'fresno'})
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST PLANT' in names
        assert 'TEST GAS STATION' not in names

    def test_city_filter(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url, {'city': 'fresno'})
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST PLANT' in names
        assert 'TEST GAS STATION' not in names

    def test_zipcode_filter(self):
        url = reverse('api:v2:ceidars:list')
        response = self.client.get(url, {'zipcode': '93728'})
        assert response.status_code == 200
        names = [d['name'] for d in response.json()['data']]
        assert 'TEST PLANT' in names
        assert 'TEST GAS STATION' not in names


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

    def test_empty_when_no_records(self, client, db):
        url = reverse('api:v2:ceidars:list')
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['data'] == []

