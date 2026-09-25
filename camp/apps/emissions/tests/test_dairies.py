import pytest

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, cepam, dairies
from camp.apps.emissions.models import CountyInventory, Dairy, DairyHerd, Digester, animal_units
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.regions.models import Region

# Beside TEST PLANT (-119.787, 36.737), inside AROUND_PLANT; IN_KERN is by Bakersfield.
NEAR_PLANT = (-119.785, 36.735)
ALSO_NEAR_PLANT = (-119.78, 36.74)
IN_KERN = (-119.02, 35.37)


def make_dairy(cadd_id, name, lnglat, county, herds=None, digesters=()):
    """A dairy with herds {year: {field: count}} (animal units computed) and digesters [(operational, shutdown)]."""
    dairy = Dairy.objects.create(
        cadd_id=cadd_id, place_id=cadd_id, name=name,
        address={'street': f'{cadd_id} Dairy Rd', 'city': 'Riverdale', 'zipcode': '93656'},
        point=Point(*lnglat, srid=4326), county=county, water_board='5F', cadd_version='2.0.0',
    )
    for year, counts in (herds or {}).items():
        DairyHerd.objects.create(
            dairy=dairy, year=year, milk_cows_ref_code='1', non_milking_ref_code='1',
            labeled_as_dairy=True, animal_units=animal_units(counts), **counts,
        )
    for operational, shutdown in digesters:
        Digester.objects.create(dairy=dairy, operational_year=operational, shutdown_year=shutdown, source='DDRDP')
    return dairy


def make_dairies():
    """
    BIG DAIRY by TEST PLANT in Fresno: 2022 and 2023, a digester since 2019;
    2023 is (1,100 + 200) x 1.4 + 300 = 2,120 animal units.
    SMALL DAIRY in Kern: 2023 only, 100 x 1.4 + 50 = 190 animal units, a
    digester that ran 2015-2021 (shut down in 2021).
    CLOSED DAIRY by TEST PLANT: only empty herds.
    """
    fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
    kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
    big = make_dairy(
        1, 'BIG DAIRY', NEAR_PLANT, fresno,
        herds={2022: {'milk_cows': 1000, 'dry_cows': 200}, 2023: {'milk_cows': 1100, 'dry_cows': 200, 'old_heifers': 300}},
        digesters=[(2019, None)],
    )
    small = make_dairy(
        2, 'SMALL DAIRY', IN_KERN, kern,
        herds={2023: {'milk_cows': 100, 'young_calves': 50, 'beef_cattle': None}},
        digesters=[(2015, 2021)],
    )
    closed = make_dairy(3, 'CLOSED DAIRY', ALSO_NEAR_PLANT, fresno, herds={2021: {'milk_cows': 0}, 2023: {'milk_cows': 0}})
    return big, small, closed


def dairy_inventory(county, year=2023, rog=2.0):
    """CEPAM rows for `county`: dairy cattle (rog tons/day), plus silage and feedlot cattle, which don't count."""
    common = {'county': county, 'year': year, 'inventory': cepam.INVENTORY,
              'source_type': CountyInventory.SourceType.AREAWIDE, 'source_name': 'LIVESTOCK HUSBANDRY'}
    CountyInventory.objects.create(eic='620-618-0262-0101', material_name='AGRICULTURAL WASTE',
                                   subcategory_name='DAIRY CATTLE', rog=rog, pm=0.1, nox=0.0, **common)
    CountyInventory.objects.create(eic='620-618-0263-0000', material_name='SILAGE (UNSPECIFIED)',
                                   subcategory_name='SUB-CATEGORY UNSPECIFIED', rog=5.0, **common)
    CountyInventory.objects.create(eic='620-618-0262-0103', material_name='AGRICULTURAL WASTE',
                                   subcategory_name='FEEDLOT CATTLE', rog=1.0, **common)


class DairyTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.big, self.small, self.closed = make_dairies()

    def names(self, **kwargs):
        return [herd.dairy.name for herd in dairies.table(2023, **kwargs)]


class YearAndSummaryTests(DairyTestCase):
    def test_empty_herds_are_left_out(self):
        # CLOSED DAIRY's 2021 is its only 2021 herd, and it's empty.
        assert dairies.years() == [2022, 2023]
        assert dairies.latest_year() == 2023
        assert 'CLOSED DAIRY' not in self.names()
        assert dairies.summary(2023)['dairies'] == 2

    def test_summary(self):
        summary = dairies.summary(2023)
        assert summary['dairies'] == 2 and summary['milk_cows'] == 1200 and summary['digesters'] == 1
        assert summary['animal_units'] == pytest.approx(2310)
        kern = dairies.summary(2023, county=self.kern)
        assert (kern['dairies'], kern['digesters']) == (1, 0)
        assert dairies.summary(2021) == {'dairies': 0, 'animal_units': 0, 'milk_cows': 0, 'digesters': 0}
        assert dairies.summary(None)['dairies'] == 0

    def test_digester_operating_in_a_year(self):
        assert Digester.objects.operating_in(2018).count() == 1
        assert Digester.objects.operating_in(2020).count() == 2
        # SMALL's digester shut down in 2021, so it isn't operating in 2021.
        assert Digester.objects.operating_in(2021).count() == 1

    def test_other_cattle_leave_out_blank_counts(self):
        herd = DairyHerd.objects.get(dairy=self.small, year=2023)
        assert herd.beef_cattle is None and herd.other_cattle == 50

    def test_trend(self):
        rows = dairies.trend()
        assert [(row['year'], row['dairies'], row['milk_cows']) for row in rows] == [(2022, 1, 1000), (2023, 2, 1200)]
        assert rows[1]['animal_units'] == pytest.approx(2310)

    def test_a_reimport_clears_the_cache(self):
        assert dairies.summary(2023)['milk_cows'] == 1200
        DairyHerd.objects.filter(dairy=self.small, year=2023).update(milk_cows=900)
        assert dairies.summary(2023)['milk_cows'] == 1200
        dairies.clear_caches()
        assert dairies.summary(2023)['milk_cows'] == 2000


class TableTests(DairyTestCase):
    def test_sorts(self):
        assert self.names() == ['BIG DAIRY', 'SMALL DAIRY']
        assert self.names(sort='animal_units') == ['SMALL DAIRY', 'BIG DAIRY']
        assert self.names(sort='-name') == ['SMALL DAIRY', 'BIG DAIRY']
        assert self.names(sort='county') == ['BIG DAIRY', 'SMALL DAIRY']
        assert self.names(sort='-county') == ['SMALL DAIRY', 'BIG DAIRY']
        assert self.names(sort='bogus') == ['BIG DAIRY', 'SMALL DAIRY']

    def test_search_and_digester_columns(self):
        assert self.names(q='small') == ['SMALL DAIRY']
        rows = {herd.dairy.name: herd for herd in dairies.table(2023)}
        assert rows['BIG DAIRY'].digester is True and rows['BIG DAIRY'].digester_since == 2019
        assert rows['SMALL DAIRY'].digester is False and rows['SMALL DAIRY'].digester_since is None


class AreaTests(DairyTestCase):
    def test_zip_and_tract_by_point(self):
        Region.objects.filter(type=Region.Type.ZIPCODE).delete()
        zipcode = make(Region.Type.ZIPCODE, '93706', AROUND_PLANT)
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert dairies.region_index(Region.Type.TRACT)[self.big.pk] == tract.pk
        assert self.small.pk not in dairies.region_index(Region.Type.TRACT)
        # CLOSED DAIRY is in the tract too, but has no counted herd.
        assert dairies.summary(2023, area=areas.RegionArea(tract))['dairies'] == 1
        assert dairies.summary(2023, area=areas.RegionArea(zipcode))['dairies'] == 1

    def test_county_city_and_radius(self):
        assert self.names(area=areas.RegionArea(self.kern)) == ['SMALL DAIRY']
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        assert self.names(area=areas.RegionArea(city)) == ['BIG DAIRY']
        assert self.names(area=areas.RadiusArea(36.737, -119.787, 1)) == ['BIG DAIRY']

    def test_dairy_areas(self):
        Region.objects.filter(type__in=[Region.Type.ZIPCODE, Region.Type.CITY]).delete()
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert dairies.dairy_areas(self.big) == [self.fresno, tract]
        assert dairies.dairy_areas(self.small) == [self.kern]


class CountyEmissionsTests(DairyTestCase):
    def test_dairy_cattle_only(self):
        dairy_inventory(self.fresno, rog=2.0)
        # 2.0 tons/day x 365; silage (5.0) and feedlot cattle (1.0) are left out.
        assert dairies.county_emissions(2023, POLLUTANTS['rog']) == {self.fresno.pk: pytest.approx(730)}
        assert dairies.county_emissions(2023, POLLUTANTS['nox']) == {}

    def test_county_values(self):
        dairy_inventory(self.fresno, rog=2.0)
        rows = {row['slug']: row for row in dairies.county_values(2023, POLLUTANTS['rog'])}
        assert len(rows) == 8
        miles = areas.region_sq_miles(Region.Type.COUNTY)[self.fresno.pk]
        fresno = rows['fresno']
        assert fresno['id'] == self.fresno.sqid and fresno['name'] == 'Fresno County'
        assert fresno['emissions'] == pytest.approx(730)
        assert fresno['emissions_per_sq_mi'] == pytest.approx(730 / miles)
        assert fresno['animal_units'] == pytest.approx(2120)
        assert fresno['animal_units_per_sq_mi'] == pytest.approx(2120 / miles)
        assert rows['kern']['emissions'] is None and rows['kern']['emissions_per_sq_mi'] is None
        assert rows['madera']['animal_units'] == 0


class ResolveScopeTests(DairyTestCase):
    def test_defaults_fall_back_quietly(self):
        scope, notes = dairies.resolve_scope({})
        assert (scope.year, scope.pollutant.key, scope.county, notes) == (2023, 'rog', None, [])

    def test_a_pollutant_dairies_dont_report(self):
        scope, notes = dairies.resolve_scope({'pollutant': 'nox'})
        assert scope.pollutant.key == 'rog'
        assert notes == ['Dairies report no NOx; showing ROG.']
        assert dairies.resolve_scope({'pollutant': 'bogus'})[1] == ['Dairies report no such pollutant; showing ROG.']
        assert dairies.resolve_scope({'pollutant': 'pm10'})[0].pollutant.key == 'pm10'

    def test_toxics(self):
        scope, notes = dairies.resolve_scope({'toxics': '1', 'pollutant': 'benzene'})
        assert scope.pollutant.key == 'rog' and not scope.toxics
        assert notes == ['Dairies report no toxic air contaminants; showing ROG.']

    def test_a_year_outside_cadd(self):
        for raw in ('2024', 'garbage'):
            scope, notes = dairies.resolve_scope({'year': raw})
            assert scope.year == 2023
            assert notes == ['CADD has herd data for 2022–2023; showing 2023.']
        assert dairies.resolve_scope({'year': '2022'})[0].year == 2022

    def test_county(self):
        assert dairies.resolve_scope({'county': 'kern'})[0].county == self.kern
        assert dairies.resolve_scope({'county': 'nowhere'})[0].county is None

    def test_no_data_yet(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        scope, notes = dairies.resolve_scope({'year': '2023'})
        assert scope.year is None and notes == []
