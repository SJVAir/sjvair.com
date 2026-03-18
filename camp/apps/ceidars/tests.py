import pytest
from unittest.mock import patch, MagicMock

from django.contrib.gis.geos import Point

from camp.apps.ceidars.models import Facility, EmissionsRecord
from camp.utils.geocoding import clean_address


@pytest.fixture
def facility(db):
    return Facility.objects.create(
        county_code=10,
        facid=1,
        name='TEST FACILITY',
        street='123 MAIN ST',
        city='FRESNO',
        zipcode='93701',
    )


class TestCleanAddress:
    def test_strips_unit_suffix(self):
        assert clean_address('123 MAIN ST #4') == '123 MAIN ST'

    def test_strips_apt_suffix(self):
        assert clean_address('123 MAIN ST APT 2B') == '123 MAIN ST'

    def test_strips_suite_suffix(self):
        assert clean_address('123 MAIN ST SUITE 100') == '123 MAIN ST'

    def test_preserves_normal_address(self):
        assert clean_address('123 MAIN ST') == '123 MAIN ST'

    def test_handles_non_string(self):
        assert clean_address(None) == ''

    def test_normalizes_whitespace(self):
        assert clean_address('  123 MAIN ST  ') == '123 MAIN ST'


class TestFacilityGeocode:
    def test_geocode_success(self, facility):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'features': [{'geometry': {'coordinates': [-119.7871, 36.7378]}}]
        }
        with patch('requests.get', return_value=mock_response):
            result = facility.geocode()
        assert result is True
        assert facility.position == Point(-119.7871, 36.7378, srid=4326)

    def test_geocode_no_results(self, facility):
        mock_response = MagicMock()
        mock_response.json.return_value = {'features': []}
        with patch('requests.get', return_value=mock_response):
            result = facility.geocode()
        assert result is False
        assert facility.position is None

    def test_geocode_does_not_save(self, facility):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'features': [{'geometry': {'coordinates': [-119.7871, 36.7378]}}]
        }
        with patch('requests.get', return_value=mock_response):
            facility.geocode()
        # Reload from DB — position should still be None
        facility.refresh_from_db()
        assert facility.position is None

    def test_geocode_failure_returns_false(self, facility):
        import requests as req
        with patch('requests.get', side_effect=req.RequestException):
            with patch('camp.apps.ceidars.models.time.sleep'):
                result = facility.geocode()
        assert result is False


class TestFacilityUniqueness:
    def test_unique_together(self, db):
        Facility.objects.create(county_code=10, facid=999, name='A')
        with pytest.raises(Exception):
            Facility.objects.create(county_code=10, facid=999, name='B')


class TestEmissionsRecord:
    def test_create(self, facility):
        record = EmissionsRecord.objects.create(
            facility=facility,
            year=2023,
            pm25='1.234567890123456',
            pm10='2.345678901234567',
        )
        assert record.year == 2023
        assert record.facility == facility

    def test_unique_together(self, facility):
        EmissionsRecord.objects.create(facility=facility, year=2023)
        with pytest.raises(Exception):
            EmissionsRecord.objects.create(facility=facility, year=2023)
