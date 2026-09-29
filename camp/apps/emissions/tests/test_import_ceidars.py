from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions.ceidars import normalize_city
from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region

CA_COUNTY_CODES = {
    'Fresno County': '10', 'Kern County': '15', 'Kings County': '16', 'Madera County': '20',
    'Merced County': '24', 'San Joaquin County': '39', 'Stanislaus County': '50', 'Tulare County': '54',
}

HEADER = 'CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,DISN,CHAPIS,CERR_CODE,TOGT,ROGT,COT,NOXT,SOXT,PMT,PM10T\n'
TOX_HEADER = 'CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,TS,HRA,CHINDEX,AHINDEX,DISN,CHAPIS,CERR_CODE\n'

FRESNO_CRITERIA = HEADER + '10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,SAN JOAQUIN VALLEY APCD,,,1.5,1.2,0.3,2.1,0.1,0.8,1.0\n'
FRESNO_TOXICS = TOX_HEADER + '10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,,,,,SAN JOAQUIN VALLEY APCD,,\n'

KERN_CRITERIA = HEADER + (
    '15,SJV,1,SJU,VALLEY HOSPITAL,2215 TRUXTUN AVE,BAKERSFIELD,93301,8062,KER,SAN JOAQUIN VALLEY APCD,,,1.0,1.0,1.0,1.0,1.0,1.0,1.0\n'
    '15,MD,1,KER,DESERT QUARRY,7037 TROTTER AVE,MOJAVE,93501,1422,KER,EASTERN KERN APCD,,,2.0,2.0,2.0,2.0,2.0,2.0,2.0\n'
)
KERN_TOXICS = TOX_HEADER + (
    '15,SJV,1,SJU,VALLEY HOSPITAL,2215 TRUXTUN AVE,BAKERSFIELD,93301,8062,KER,,,,,SAN JOAQUIN VALLEY APCD,,\n'
    '15,MD,1,KER,DESERT QUARRY,7037 TROTTER AVE,MOJAVE,93501,1422,KER,,,,,EASTERN KERN APCD,,\n'
)

POINT = Point(-119.787, 36.737, srid=4326)


def carb(criteria_by_county, toxics_by_county, urls=None):
    """A requests.get stand-in serving CARB CSVs by county code (`co_=`)."""

    def get(url, **kwargs):
        if urls is not None:
            urls.append(url)
        county = int(url.split('co_=')[1].split('&')[0])
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        if 'faccrit' in url:
            mock.text = criteria_by_county.get(county, '')
        else:
            mock.text = toxics_by_county.get(county, '')
        return mock
    return get


CARB_POINT = Point(-119.79, 36.74, srid=4326)


def census_all(addresses, **kwargs):
    return [(address, POINT) for address in addresses]


def none_found(addresses, **kwargs):
    return [(address, None) for address in addresses]


class ImportCeidarsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        # Start from no facilities: the fixture is here for its district Regions.
        EmissionsRecord.objects.all().delete()
        Facility.objects.all().delete()
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])

    def run_import(self, year=2024, county=None, criteria=None, toxics=None, urls=None,
                   census=census_all, maptiler=none_found, markers=None, regeocode=False, crawl_toxics=False):
        criteria = criteria if criteria is not None else {10: FRESNO_CRITERIA, 15: KERN_CRITERIA}
        toxics = toxics if toxics is not None else {10: FRESNO_TOXICS, 15: KERN_TOXICS}
        with patch('requests.get', side_effect=carb(criteria, toxics, urls)), \
                patch('camp.apps.emissions.pmt.fetch_markers', return_value=(markers or {}, [2024])), \
                patch('camp.utils.geocode.census_batch', side_effect=census), \
                patch('camp.utils.geocode.maptiler_batch', side_effect=maptiler) as maptiler_mock:
            kwargs = {'year': year}
            if county:
                kwargs['county'] = county
            if regeocode:
                kwargs['regeocode'] = True
            if not crawl_toxics:
                kwargs['skip_toxics'] = True
            call_command('import_ceidars', **kwargs)
        return maptiler_mock

    def test_creates_facility_and_record(self):
        self.run_import(county='fresno')
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.air_district.external_id == 'SJU'
        assert facility.county.name == 'Fresno County'
        assert facility.point == POINT
        record = facility.emissions.get(year=2024)
        assert record.tog == Decimal('1.5')
        assert record.pm == Decimal('0.8')
        assert record.pm10 == Decimal('1.0')

    def test_requests_whole_counties(self):
        urls = []
        self.run_import(county='kern', urls=urls)
        assert urls
        for url in urls:
            assert 'co_=15' in url
            assert 'ab_=' not in url
            assert 'dis_=' not in url

    def test_covers_every_county_region_by_default(self):
        urls = []
        self.run_import(urls=urls)
        requested = {int(url.split('co_=')[1].split('&')[0]) for url in urls}
        expected = {int(county.metadata['ca_county_code']) for county in Region.objects.counties()}
        assert expected
        assert requested == expected

    def test_same_facid_in_two_districts(self):
        self.run_import(county='kern')
        valley = Facility.objects.get(county_code=15, air_district__external_id='SJU', facid=1)
        desert = Facility.objects.get(county_code=15, air_district__external_id='KER', facid=1)
        assert valley.name == 'VALLEY HOSPITAL'
        assert desert.name == 'DESERT QUARRY'
        assert valley.emissions.get(year=2024).nox == Decimal('1.0')
        assert desert.emissions.get(year=2024).nox == Decimal('2.0')

    def test_no_per_pollutant_requests(self):
        urls = []
        self.run_import(county='fresno', urls=urls)
        assert urls and all('showpol' not in url and 'facdet' not in url for url in urls)

    def test_rerun_is_idempotent(self):
        self.run_import(county='kern')
        self.run_import(county='kern')
        assert Facility.objects.count() == 2
        assert EmissionsRecord.objects.count() == 2

    def test_older_year_does_not_overwrite_newer_metadata(self):
        self.run_import(county='fresno', year=2024)
        older = {10: FRESNO_CRITERIA.replace('TEST FACILITY A', 'OLD NAME')}
        self.run_import(county='fresno', year=2023, criteria=older)
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.metadata_year == 2024
        assert facility.emissions.count() == 2

    def test_geocode_failure_does_not_abort(self):
        self.run_import(county='fresno', census=none_found)
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point is None
        assert facility.emissions.count() == 1

    def test_point_source_records_which_geocoder_answered(self):
        self.run_import(county='fresno')
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.CENSUS
        Facility.objects.all().delete()
        self.run_import(county='fresno', census=none_found, maptiler=census_all)
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.MAPTILER

    def test_runs_the_toxics_crawl_for_the_same_year_and_county(self):
        with patch('camp.apps.emissions.management.commands.import_ceidars.call_command') as crawl:
            self.run_import(county='fresno', crawl_toxics=True)
        assert crawl.call_args.args == ('import_toxics',)
        assert (crawl.call_args.kwargs['year'], crawl.call_args.kwargs['county']) == (2024, 'fresno')
        with patch('camp.apps.emissions.management.commands.import_ceidars.call_command') as crawl:
            self.run_import(county='fresno')
        assert not crawl.called

    def test_carb_coordinates_come_before_maptiler(self):
        maptiler = self.run_import(county='fresno', census=none_found, maptiler=census_all, markers={(10, 'SJU', 1): CARB_POINT})
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point.equals_exact(CARB_POINT, 1e-9) and facility.point_source == Facility.PointSource.CARB
        assert maptiler.call_args.args[0] == []  # no MapTiler request for a facility CARB placed

    def test_a_census_street_match_beats_carb(self):
        self.run_import(county='fresno', markers={(10, 'SJU', 1): CARB_POINT})
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point == POINT and facility.point_source == Facility.PointSource.CENSUS

    def test_an_untrusted_point_is_upgraded_on_the_next_run(self):
        self.run_import(county='fresno', census=none_found, maptiler=census_all)
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.MAPTILER
        self.run_import(county='fresno', census=none_found, markers={(10, 'SJU', 1): CARB_POINT})
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.CARB

    def test_a_legacy_point_with_nothing_better_is_kept(self):
        self.run_import(county='fresno')
        Facility.objects.filter(county_code=10, facid=1).update(point_source=Facility.PointSource.LEGACY)
        self.run_import(county='fresno', census=none_found)
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point == POINT and facility.point_source == Facility.PointSource.LEGACY

    def test_a_trusted_point_is_left_alone_without_regeocode(self):
        self.run_import(county='fresno')
        located = []

        def census(addresses, **kwargs):
            located.extend(addresses)
            return census_all(addresses)

        self.run_import(county='fresno', census=census)
        assert located == []
        self.run_import(county='fresno', census=census, regeocode=True)
        assert [address['street'] for address in located] == ['123 MAIN ST']

    def test_no_point_means_no_source(self):
        self.run_import(county='fresno', census=lambda addresses, **kwargs: [])
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point is None and facility.point_source == ''

    def test_unknown_district_fails_that_county_and_writes_nothing(self):
        Facility.objects.filter(air_district__external_id='KER').delete()
        Region.objects.filter(external_id='KER', type=Region.Type.AIR_DISTRICT).delete()
        with pytest.raises(CommandError, match='Kern County'):
            self.run_import()
        assert not Facility.objects.filter(county_code=15).exists()
        assert Facility.objects.filter(county_code=10).exists()

    def test_county_without_carb_code_is_an_error(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        fresno.metadata.pop('ca_county_code')
        fresno.save(update_fields=['metadata'])
        with pytest.raises(CommandError, match='import_counties'):
            self.run_import(county='fresno')

    def test_unknown_county_slug_is_an_error(self):
        with pytest.raises(CommandError, match='nowhere'):
            self.run_import(county='nowhere')

    def test_point_outside_the_county_is_dropped(self):
        slovakia = Point(19.174, 48.741, srid=4326)
        self.run_import(county='fresno', census=lambda addresses, **kw: [(a, slovakia) for a in addresses])
        assert Facility.objects.get(county_code=10, facid=1).point is None

    def test_various_locations_are_not_geocoded(self):
        placeholder = ('123 MAIN ST,FRESNO', 'VARIOUS LOCATIONS,VARIOUS LOCATIONS')
        criteria = {10: FRESNO_CRITERIA.replace(*placeholder)}
        toxics = {10: FRESNO_TOXICS.replace(*placeholder)}
        geocoded = []

        def geocode(addresses, **kw):
            geocoded.extend(addresses)
            return [(a, POINT) for a in addresses]

        self.run_import(county='fresno', criteria=criteria, toxics=toxics, census=geocode, maptiler=geocode)
        assert geocoded == []
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point is None
        assert facility.emissions.count() == 1

    def test_sets_sector_from_sic(self):
        self.run_import(county='fresno')
        assert Facility.objects.get(county_code=10, facid=1).sector == Facility.Sector.POWER_PLANTS


class NormalizeCityTests(TestCase):
    def lookup(self, *names):
        return {name.upper(): name for name in names}

    def test_clean_match(self):
        assert normalize_city('FRESNO', self.lookup('Fresno')) == 'Fresno'

    def test_strips_ca_suffix(self):
        lookup = self.lookup('Bakersfield')
        assert normalize_city('BAKERSFIELD CA', lookup) == 'Bakersfield'
        assert normalize_city('BAKERSFIELD, CA', lookup) == 'Bakersfield'

    def test_applies_corrections(self):
        lookup = self.lookup('Porterville', 'McFarland', "O'Neals", 'Kettleman City')
        assert normalize_city('PORTERVILE', lookup) == 'Porterville'
        assert normalize_city('MC FARLAND', lookup) == 'McFarland'
        assert normalize_city('ONEALS', lookup) == "O'Neals"
        assert normalize_city('KETTLEMAN', lookup) == 'Kettleman City'

    def test_non_city_strings_return_none(self):
        lookup = self.lookup('Fresno')
        for value in ('FRESNO COUNTY', 'SJVAPCD', 'SEC 13 R27S R34E', 'W/O TAFT', 'SITE NEAR SANGER'):
            assert normalize_city(value, lookup) is None

    def test_empty_or_unmatched_returns_none(self):
        assert normalize_city('', {}) is None
        assert normalize_city('FRESNO', {}) is None
