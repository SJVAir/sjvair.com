import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.gis.geos import Point
from django.core.management import call_command

from camp.apps.ceidars.models import Facility, EmissionsRecord
from camp.utils.geocode import clean_address


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
    def test_geocode_success_via_census(self, facility):
        point = Point(-119.7871, 36.7378, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            result = facility.geocode()
        assert result is True
        assert facility.position == point

    def test_geocode_falls_back_to_maptiler(self, facility):
        point = Point(-119.7871, 36.7378, srid=4326)
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=point):
                result = facility.geocode()
        assert result is True
        assert facility.position == point

    def test_geocode_no_results(self, facility):
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=None):
                result = facility.geocode()
        assert result is False
        assert facility.position is None

    def test_geocode_does_not_save(self, facility):
        point = Point(-119.7871, 36.7378, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            facility.geocode()
        facility.refresh_from_db()
        assert facility.position is None

    def test_geocode_failure_returns_false(self, facility):
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=None):
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


# ---- Import command tests ----

CRITERIA_CSV = """CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,DISN,CHAPIS,CERR_CODE,TOGT,ROGT,COT,NOXT,SOXT,PMT,PM10T
10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,SAN JOAQUIN VALLEY APCD,,,1.5,1.2,0.3,2.1,0.1,0.8,1.0
"""

TOXICS_CSV = """CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,TS,HRA,CHINDEX,AHINDEX,DISN,CHAPIS,CERR_CODE
10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,,,,,SAN JOAQUIN VALLEY APCD,,
"""

_TEST_POINT = Point(-119.787, 36.737, srid=4326)


def mock_fetch(criteria_csv=CRITERIA_CSV, toxics_csv=TOXICS_CSV):
    """Returns a mock for requests.get that serves the CARB test CSVs."""
    def _fetch(url, **kwargs):
        mock = MagicMock()
        if 'faccrit' in url:
            mock.text = criteria_csv
        else:
            mock.text = toxics_csv
        mock.raise_for_status.return_value = None
        return mock
    return _fetch


class TestImportCommand:
    def test_creates_facility_and_emissions_record(self, db):
        with patch('requests.get', side_effect=mock_fetch()):
            with patch('camp.utils.geocode.batch', return_value=[_TEST_POINT]):
                call_command('import_ceidars', year=2023, county=10)

        assert Facility.objects.count() == 1
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.metadata_year == 2023
        assert facility.position == _TEST_POINT

        assert EmissionsRecord.objects.count() == 1
        record = EmissionsRecord.objects.get(facility=facility, year=2023)
        assert record.tog == Decimal('1.5')
        assert record.pm25 == Decimal('0.8')

    def test_idempotent_rerun(self, db):
        with patch('requests.get', side_effect=mock_fetch()):
            with patch('camp.utils.geocode.batch', return_value=[_TEST_POINT]):
                call_command('import_ceidars', year=2023, county=10)
                # Second run: facility exists, batch not called (no new facilities)
                call_command('import_ceidars', year=2023, county=10)

        assert Facility.objects.count() == 1
        assert EmissionsRecord.objects.count() == 1

    def test_metadata_year_guard_prevents_older_overwrite(self, db):
        criteria_2022 = CRITERIA_CSV.replace('TEST FACILITY A', 'OLD NAME')
        with patch('requests.get', side_effect=mock_fetch()):
            with patch('camp.utils.geocode.batch', return_value=[_TEST_POINT]):
                call_command('import_ceidars', year=2023, county=10)

        with patch('requests.get', side_effect=mock_fetch(criteria_csv=criteria_2022)):
            call_command('import_ceidars', year=2022, county=10)

        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.metadata_year == 2023
        assert EmissionsRecord.objects.count() == 2

    def test_geocode_failure_does_not_abort(self, db):
        with patch('requests.get', side_effect=mock_fetch()):
            with patch('camp.utils.geocode.batch', return_value=[None]):
                with patch('camp.utils.geocode.maptiler', return_value=None):
                    call_command('import_ceidars', year=2023, county=10)

        assert Facility.objects.count() == 1
        assert Facility.objects.first().position is None
        assert EmissionsRecord.objects.count() == 1
