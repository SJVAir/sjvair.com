import pytest
from datetime import datetime
from unittest.mock import patch

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase
from django.utils.timezone import make_aware
from zoneinfo import ZoneInfo

from camp.apps.pesticides.models import Chemical, SprayApplication
from camp.apps.pesticides.spraydays import (
    SprayDaysClient,
    comtr_from_mtrs,
    fetch_applications,
)
from camp.apps.regions.models import Boundary, Region

PT = ZoneInfo('America/Los_Angeles')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresno_county(db):
    region = Region.objects.create(
        name='Fresno County',
        slug='fresno-county',
        type=Region.Type.COUNTY,
        external_id='fresno-county',
    )
    poly = Polygon((
        (-121.0, 35.8), (-118.3, 35.8),
        (-118.3, 37.6), (-121.0, 37.6),
        (-121.0, 35.8),
    ), srid=4326)
    boundary = Boundary.objects.create(
        region=region,
        version='test',
        geometry=MultiPolygon(poly, srid=4326),
    )
    region.boundary = boundary
    region.save()
    return region


@pytest.fixture
def mtrs_region(db):
    """MTRS region with a boundary polygon that covers TEST_LON, TEST_LAT."""
    region = Region.objects.create(
        name='MDM-T17S-R16E-08',
        slug='mdm-t17s-r16e-08',
        external_id='MDM-T17S-R16E-08',
        type=Region.Type.MTRS,
    )
    poly = Polygon((
        (-120.0, 36.3), (-119.6, 36.3),
        (-119.6, 36.7), (-120.0, 36.7),
        (-120.0, 36.3),
    ), srid=4326)
    boundary = Boundary.objects.create(
        region=region,
        version='test',
        geometry=MultiPolygon(poly, srid=4326),
    )
    region.boundary = boundary
    region.save()
    return region


@pytest.fixture
def chemical(db):
    return Chemical.objects.create(chem_code=383, name='METHOMYL')


# Test coordinates fall inside the mtrs_region boundary above
TEST_LAT = 36.5
TEST_LON = -119.8

MOCK_COUNTY_DATA = [{'CountyId': 10, 'ApplicationCount': 1}]
MOCK_NOI_POINTS = [{'Latitude': TEST_LAT, 'Longitude': TEST_LON}]
MOCK_APPLICATION = {
    'Id': 2058111,
    'ScheduledApplicationFormatted': '05/15/2026 08:00:00 AM',
    'TreatedAmount': 33.75,
    'TreatedUnits': 'Acres',
    'ApplicationMethod': 'Ground',
    'Products': [{
        'ProductName': 'NUDRIN SP',
        'EPARegNo': '83100-28-ZA-83979',
        'Chemicals': [{'ChemicalName': 'METHOMYL', 'ChemicalCode': '383'}],
    }],
}


def mock_client(active_counties=None, noi_points=None, applications=None):
    """Patch all three SprayDaysClient network methods."""
    return (
        patch.object(SprayDaysClient, 'authenticate'),
        patch.object(SprayDaysClient, 'get_active_counties',
                     return_value=active_counties or MOCK_COUNTY_DATA),
        patch.object(SprayDaysClient, 'get_noi_locations',
                     return_value=noi_points or MOCK_NOI_POINTS),
        patch.object(SprayDaysClient, 'get_applications',
                     return_value=applications or [MOCK_APPLICATION]),
    )


# ---------------------------------------------------------------------------
# comtr_from_mtrs
# ---------------------------------------------------------------------------

class TestComtrFromMtrs:
    def test_south_range(self):
        assert comtr_from_mtrs('MDM-T17S-R16E-08', '10') == '1017S16E08'

    def test_north_range(self):
        assert comtr_from_mtrs('MDM-T01N-R04E-01', '15') == '1501N04E01'

    def test_west_range(self):
        assert comtr_from_mtrs('MDM-T05S-R03W-12', '39') == '3905S03W12'

    def test_pads_single_digit_township(self):
        assert comtr_from_mtrs('MDM-T01S-R01E-01', '10') == '1001S01E01'

    def test_invalid_returns_none(self):
        assert comtr_from_mtrs('NOT-A-VALID-ID', '10') is None

    def test_empty_returns_none(self):
        assert comtr_from_mtrs('', '10') is None


# ---------------------------------------------------------------------------
# fetch_applications
# ---------------------------------------------------------------------------

class TestFetchApplications:
    def test_creates_application(self, fresno_county, mtrs_region, chemical):
        auth, active, noi, apps = mock_client()
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 1
        assert updated == 0

        app = SprayApplication.objects.get(application_id=2058111)
        assert app.comtr == '1017S16E08'
        assert app.county == fresno_county
        assert app.mtrs == mtrs_region
        assert app.treated_amount == 33.75
        assert app.treated_units == 'Acres'
        assert app.application_method == 'Ground'
        assert chemical in app.chemicals.all()
        assert app.scheduled_application == make_aware(
            datetime(2026, 5, 15, 8, 0, 0), PT
        )

    def test_upserts_on_second_run(self, fresno_county, mtrs_region, chemical):
        auth, active, noi, apps = mock_client()
        with auth, active, noi, apps:
            fetch_applications()

        modified_app = {**MOCK_APPLICATION, 'TreatedAmount': 50.0}
        auth, active, noi, apps = mock_client(applications=[modified_app])
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 0
        assert updated == 1
        assert SprayApplication.objects.get(application_id=2058111).treated_amount == 50.0

    def test_skips_unparseable_date(self, fresno_county, mtrs_region, db):
        bad_app = {**MOCK_APPLICATION, 'ScheduledApplicationFormatted': 'not-a-date'}
        auth, active, noi, apps = mock_client(applications=[bad_app])
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 0
        assert SprayApplication.objects.count() == 0

    def test_unknown_chemical_code_is_ignored(self, fresno_county, mtrs_region, db):
        app = {**MOCK_APPLICATION, 'Products': [{
            'ProductName': 'UNKNOWN PRODUCT',
            'EPARegNo': '999-999',
            'Chemicals': [{'ChemicalName': 'MYSTERY CHEM', 'ChemicalCode': '99999'}],
        }]}
        auth, active, noi, apps = mock_client(applications=[app])
        with auth, active, noi, apps:
            created, _ = fetch_applications()

        assert created == 1
        spray = SprayApplication.objects.get(application_id=2058111)
        assert spray.chemicals.count() == 0

    def test_deduplicates_comtr_across_noi_pins(self, fresno_county, mtrs_region, db):
        # Two NOI pins in the same MTRS section → only one GetApplications call
        two_pins = [
            {'Latitude': TEST_LAT, 'Longitude': TEST_LON},
            {'Latitude': TEST_LAT + 0.01, 'Longitude': TEST_LON + 0.01},
        ]
        with patch.object(SprayDaysClient, 'authenticate'), \
             patch.object(SprayDaysClient, 'get_active_counties', return_value=MOCK_COUNTY_DATA), \
             patch.object(SprayDaysClient, 'get_noi_locations', return_value=two_pins), \
             patch.object(SprayDaysClient, 'get_applications', return_value=[MOCK_APPLICATION]) as mock_apps:
            fetch_applications()
        mock_apps.assert_called_once()

    def test_county_filter_skips_other_counties(self, fresno_county, mtrs_region, db):
        # API returns Fresno (10); we filter to Kern (15) → nothing fetched
        auth, active, noi, apps = mock_client()
        with auth, active, noi, apps:
            fetch_applications(county_filter='15')

        assert SprayApplication.objects.count() == 0

    def test_no_mtrs_match_skips_pin(self, fresno_county, db):
        # NOI pin outside any MTRS boundary → no application created
        out_of_bounds = [{'Latitude': 0.0, 'Longitude': 0.0}]
        auth, active, noi, apps = mock_client(noi_points=out_of_bounds)
        with auth, active, noi, apps:
            created, _ = fetch_applications()

        assert created == 0

    def test_empty_county_list_is_no_op(self, db):
        auth, active, noi, apps = mock_client(active_counties=[])
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 0
        assert updated == 0


# ---------------------------------------------------------------------------
# SprayApplication model
# ---------------------------------------------------------------------------

class TestSprayApplicationModel:
    def test_application_id_is_unique(self, fresno_county, db):
        SprayApplication.objects.create(
            application_id=1,
            comtr='1017S16E08',
            county=fresno_county,
            scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
        )
        with pytest.raises(Exception):
            SprayApplication.objects.create(
                application_id=1,
                comtr='1017S16E08',
                county=fresno_county,
                scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
            )

    def test_str(self, fresno_county, db):
        app = SprayApplication.objects.create(
            application_id=42,
            comtr='1017S16E08',
            county=fresno_county,
            scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
        )
        assert str(app) == '42 / 1017S16E08'
