import pytest
from datetime import datetime
from unittest.mock import patch

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase
from django.utils.timezone import make_aware
from zoneinfo import ZoneInfo

from camp.apps.pesticides.models import Chemical, Commodity, PesticideUse, Product, PesticideNotice
from camp.apps.regions.models import Region
from camp.apps.pesticides.spraydays import (
    SprayDaysClient,
    comtrs_from_mtrs,
    fetch_applications,
    SJV_COUNTY_CODES,
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
        slug='fresno',
        type=Region.Type.COUNTY,
        external_id='06019',
        metadata={'ca_county_code': '10'},
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


@pytest.fixture
def product(db):
    return Product.objects.create(
        prodno=1,
        reg_number='83100-28-ZA-83979',
        name='NUDRIN SP',
    )


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
# comtrs_from_mtrs
# ---------------------------------------------------------------------------

class TestComtrsFromMtrs:
    def test_south_range(self):
        assert comtrs_from_mtrs('MDM-T17S-R16E-08', '10') == '1017S16E08'

    def test_north_range(self):
        assert comtrs_from_mtrs('MDM-T01N-R04E-01', '15') == '1501N04E01'

    def test_west_range(self):
        assert comtrs_from_mtrs('MDM-T05S-R03W-12', '39') == '3905S03W12'

    def test_pads_single_digit_township(self):
        assert comtrs_from_mtrs('MDM-T01S-R01E-01', '10') == '1001S01E01'

    def test_invalid_returns_none(self):
        assert comtrs_from_mtrs('NOT-A-VALID-ID', '10') is None

    def test_empty_returns_none(self):
        assert comtrs_from_mtrs('', '10') is None


# ---------------------------------------------------------------------------
# fetch_applications
# ---------------------------------------------------------------------------

class TestFetchApplications:
    def test_creates_application(self, fresno_county, mtrs_region, chemical, product):
        auth, active, noi, apps = mock_client()
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 1
        assert updated == 0

        app = PesticideNotice.objects.get(application_id=2058111)
        assert app.comtrs == '1017S16E08'
        assert app.county == fresno_county
        assert app.mtrs == mtrs_region
        assert app.treated_amount == 33.75
        assert app.treated_units == 'Acres'
        assert app.application_method == 'Ground'
        assert chemical in app.chemicals.all()
        assert product in app.products.all()
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
        assert PesticideNotice.objects.get(application_id=2058111).treated_amount == 50.0

    def test_skips_unparseable_date(self, fresno_county, mtrs_region, db):
        bad_app = {**MOCK_APPLICATION, 'ScheduledApplicationFormatted': 'not-a-date'}
        auth, active, noi, apps = mock_client(applications=[bad_app])
        with auth, active, noi, apps:
            created, updated = fetch_applications()

        assert created == 0
        assert PesticideNotice.objects.count() == 0

    def test_unknown_product_reg_no_is_ignored(self, fresno_county, mtrs_region, db):
        auth, active, noi, apps = mock_client()
        with auth, active, noi, apps:
            created, _ = fetch_applications()

        assert created == 1
        spray = PesticideNotice.objects.get(application_id=2058111)
        assert spray.products.count() == 0

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
        spray = PesticideNotice.objects.get(application_id=2058111)
        assert spray.chemicals.count() == 0

    def test_deduplicates_comtrs_across_noi_pins(self, fresno_county, mtrs_region, db):
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

        assert PesticideNotice.objects.count() == 0

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
# PesticideNotice model
# ---------------------------------------------------------------------------

class TestPesticideNoticeModel:
    def test_application_id_is_unique(self, fresno_county, db):
        PesticideNotice.objects.create(
            application_id=1,
            comtrs='1017S16E08',
            county=fresno_county,
            scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
        )
        with pytest.raises(Exception):
            PesticideNotice.objects.create(
                application_id=1,
                comtrs='1017S16E08',
                county=fresno_county,
                scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
            )

    def test_str(self, fresno_county, db):
        app = PesticideNotice.objects.create(
            application_id=42,
            comtrs='1017S16E08',
            county=fresno_county,
            scheduled_application=make_aware(datetime(2026, 5, 15, 8, 0), PT),
        )
        assert str(app) == '42 / 1017S16E08'


# ---------------------------------------------------------------------------
# Chemical model
# ---------------------------------------------------------------------------

class ChemicalModelTests(TestCase):
    def test_str(self):
        chem = Chemical.objects.create(chem_code=383, name='METHOMYL')
        assert str(chem) == 'METHOMYL'

    def test_categories_default_empty(self):
        chem = Chemical.objects.create(chem_code=9999, name='TEST')
        assert chem.categories == []

    def test_iarc_group_blank_by_default(self):
        chem = Chemical.objects.create(chem_code=9998, name='TEST2')
        assert chem.iarc_group == ''

    def test_dtxsid_blank_by_default(self):
        chem = Chemical.objects.create(chem_code=9997, name='TEST3')
        assert chem.dtxsid == ''


# ---------------------------------------------------------------------------
# M2M relations through PesticideUse
# ---------------------------------------------------------------------------

class ChemicalCommoditiesM2MTests(TestCase):
    def setUp(self):
        self.county = Region.objects.create(
            name='Fresno County', slug='fresno',
            type=Region.Type.COUNTY, external_id='06019',
            metadata={'ca_county_code': '10'},
        )
        self.chemical = Chemical.objects.create(chem_code=383, name='METHOMYL')
        self.commodity = Commodity.objects.create(site_code='01', name='ALMOND')
        self.use = PesticideUse.objects.create(
            year=2023, use_no=1,
            county=self.county,
            chemical=self.chemical,
            commodity=self.commodity,
        )

    def test_commodity_accessible_via_m2m(self):
        assert self.commodity in self.chemical.commodities.all()

    def test_requires_distinct_for_unique_results(self):
        # Multiple PesticideUse rows with same pair — raw .count() returns row count,
        # .distinct().count() returns unique commodities.
        for i in range(3):
            PesticideUse.objects.create(
                year=2023, use_no=i + 10,
                county=self.county,
                chemical=self.chemical,
                commodity=self.commodity,
            )
        assert self.chemical.commodities.distinct().count() == 1

    def test_use_without_commodity_is_excluded(self):
        chemical2 = Chemical.objects.create(chem_code=999, name='OTHER')
        PesticideUse.objects.create(year=2023, use_no=99, county=self.county, chemical=chemical2)
        assert chemical2.commodities.count() == 0

    def test_reverse_chemicals_on_commodity(self):
        assert self.chemical in self.commodity.chemicals.all()

    def test_reverse_requires_distinct(self):
        for i in range(3):
            PesticideUse.objects.create(
                year=2023, use_no=i + 10,
                county=self.county,
                chemical=self.chemical,
                commodity=self.commodity,
            )
        assert self.commodity.chemicals.distinct().count() == 1


class ProductCommoditiesM2MTests(TestCase):
    def setUp(self):
        self.county = Region.objects.create(
            name='Fresno County', slug='fresno',
            type=Region.Type.COUNTY, external_id='06019',
            metadata={'ca_county_code': '10'},
        )
        self.product = Product.objects.create(prodno=1, reg_number='83100-28', name='NUDRIN SP')
        self.commodity = Commodity.objects.create(site_code='01', name='ALMOND')
        self.use = PesticideUse.objects.create(
            year=2023, use_no=1,
            county=self.county,
            product=self.product,
            commodity=self.commodity,
        )

    def test_commodity_accessible_via_m2m(self):
        assert self.commodity in self.product.commodities.all()

    def test_requires_distinct_for_unique_results(self):
        for i in range(3):
            PesticideUse.objects.create(
                year=2023, use_no=i + 10,
                county=self.county,
                product=self.product,
                commodity=self.commodity,
            )
        assert self.product.commodities.distinct().count() == 1

    def test_reverse_products_on_commodity(self):
        assert self.product in self.commodity.products.all()

    def test_use_without_commodity_is_excluded(self):
        product2 = Product.objects.create(prodno=2, reg_number='999-1', name='OTHER')
        PesticideUse.objects.create(year=2023, use_no=99, county=self.county, product=product2)
        assert product2.commodities.count() == 0


# ---------------------------------------------------------------------------
# Queryset with_* filter tests
# ---------------------------------------------------------------------------

class WithChemicalsFilterTests(TestCase):
    def setUp(self):
        self.county = Region.objects.create(
            name='Fresno County', slug='fresno',
            type=Region.Type.COUNTY, external_id='06019',
            metadata={'ca_county_code': '10'},
        )
        self.glyphosate = Chemical.objects.create(chem_code=417, name='GLYPHOSATE')
        self.copper = Chemical.objects.create(chem_code=100, name='COPPER SULFATE')
        self.almond = Commodity.objects.create(site_code='01', name='ALMOND')
        self.grape = Commodity.objects.create(site_code='02', name='GRAPE')

        # Glyphosate → Almond in 2022, Glyphosate → Grape in 2023
        PesticideUse.objects.create(year=2022, use_no=1, county=self.county,
            chemical=self.glyphosate, commodity=self.almond)
        PesticideUse.objects.create(year=2023, use_no=2, county=self.county,
            chemical=self.glyphosate, commodity=self.grape)

        # Copper → Almond in 2023
        PesticideUse.objects.create(year=2023, use_no=3, county=self.county,
            chemical=self.copper, commodity=self.almond)

    def _almond(self):
        return Commodity.objects.with_chemicals(pesticide_uses__year=2023).get(pk=self.almond.pk)

    def test_matched_chemical_is_returned(self):
        # Copper was used on Almond in 2023 — should appear
        assert self.copper in self._almond().chemicals.all()

    def test_cross_commodity_false_positive(self):
        # Glyphosate was used on Almond in 2022 and on Grape in 2023 —
        # should NOT appear in Almond's chemicals when filtered to 2023
        assert self.glyphosate not in self._almond().chemicals.all()
