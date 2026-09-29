"""
guardian-2024.csv is CARB's real facdet CSV for Guardian Industries (Fresno,
SJU, facid 598), fetched 2026-09-28:
  curl 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=SJV&dis_=SJU&co_=10&sort=T&facid_=598'
health-values.json is `import_health_values --dump` of the 2024-12-17 table.
"""
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import contable, stats
from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, ToxicEmission, ToxicPollutant
from camp.apps.emissions.tests.test_import_ceidars import CA_COUNTY_CODES
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data'
HEADER = '"FACID","CO","AB","DIS","POLLUTANT_ID","POLLUTANT","EMISSIONS_LBS_YR"\n'


def facdet(rows_by_facid, failing=()):
    """A requests.get stand-in serving facdet CSVs by facid_=; raises for `failing` facids."""
    def get(url, **kwargs):
        facid = int(url.split('facid_=')[1].split('&')[0])
        if facid in failing:
            raise requests.ConnectionError('boom')
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.text = rows_by_facid.get(facid, HEADER)
        return mock
    return get


class ImportToxicsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])
        self.plant = Facility.objects.get(name='TEST PLANT')      # Fresno, SJU, facid 1
        self.cement = Facility.objects.get(name='TEST CEMENT')    # Kern, KER, facid 2
        self.gas = Facility.objects.get(name='TEST GAS STATION')  # Kern, SJU, facid 2

    def run_import(self, rows_by_facid, county=None, failing=(), urls=None):
        stub = facdet(rows_by_facid, failing)

        def get(url, **kwargs):
            if urls is not None:
                urls.append(url)
            return stub(url, **kwargs)

        with patch('requests.get', side_effect=get):
            kwargs = {'year': 2024, 'workers': 2}
            if county:
                kwargs['county'] = county
            call_command('import_toxics', **kwargs)

    def test_replaces_a_facilitys_rows_and_creates_unknown_pollutants(self):
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n1,10,"SJV","SJU",9901,"Diesel PM",12\n1,10,"SJV","SJU",108883,"TOLUENE",7.25\n'
        self.run_import({1: csv}, county='fresno')
        rows = {row.pollutant.carb_id: row.lbs for row in self.plant.toxic_emissions.filter(year=2024)}
        assert rows == {'71432': Decimal('3.5'), '9901': Decimal('12'), '108883': Decimal('7.25')}
        toluene = ToxicPollutant.objects.get(carb_id='108883')
        assert (toluene.name, toluene.slug, toluene.cas_number, toluene.kind) == ('Toluene', 'toluene', '108-88-3', 'toxic')
        # The fixture's ammonia and isopropyl rows for 2024 were replaced; 2023 is untouched.
        assert self.plant.toxic_emissions.filter(year=2023).count() == 1
        stamp = SourceImport.latest('ceidars-toxics')
        assert stamp.version == '2024' and stamp.notes['facilities'] == 1

    def test_rerun_is_idempotent(self):
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n'
        self.run_import({1: csv}, county='fresno')
        self.run_import({1: csv}, county='fresno')
        assert self.plant.toxic_emissions.filter(year=2024).count() == 1

    def test_urls_carry_basin_district_county_and_facid(self):
        urls = []
        self.run_import({}, county='kern', urls=urls)
        assert sorted(urls) == sorted([
            'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=MD&dis_=KER&co_=15&sort=T&facid_=2',
            'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=SJV&dis_=SJU&co_=15&sort=T&facid_=2',
        ])

    def test_an_empty_csv_clears_the_year(self):
        self.run_import({}, county='fresno')
        assert not self.plant.toxic_emissions.filter(year=2024).exists()

    def test_a_failed_facility_is_skipped_and_the_rest_land(self):
        # Kern has two facilities with the same facid in two districts; fail both
        # Kern fetches and check Fresno still lands and Kern keeps its old rows.
        before = set(self.cement.toxic_emissions.values_list('pk', flat=True))
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n'
        with pytest.raises(CommandError, match='2 facilities'):
            self.run_import({1: csv}, failing={2})
        assert self.plant.toxic_emissions.get(year=2024, pollutant__carb_id='71432').lbs == Decimal('3.5')
        assert set(self.cement.toxic_emissions.values_list('pk', flat=True)) == before
        assert SourceImport.latest('ceidars-toxics').notes['failed'] == 2

    def test_import_bumps_the_cache_generation(self):
        before = stats.generation()
        self.run_import({}, county='fresno')
        assert stats.generation() == before + 1


class GuardianRegressionTests(TestCase):
    """CARB's own 2024 cancer score for Guardian Industries is 7,594.997; ours must land within 1."""

    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_cancer_weighted_score_matches_carb(self):
        with open(DATA / 'health-values.json') as handle:
            table = json.load(handle)
        contable.apply(table['rows'], None)
        ToxicEmission.objects.all().delete()
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        guardian = Facility.objects.create(
            county_code=10, air_district=Region.objects.get(pk=9001), facid=598, name='GUARDIAN INDUSTRIES, LLC',
            county=fresno, sic_code=3211, sector='glass', address={},
        )
        EmissionsRecord.objects.create(facility=guardian, year=2024, nox=1)
        with patch('requests.get', side_effect=facdet({598: (DATA / 'guardian-2024.csv').read_text()})):
            call_command('import_toxics', year=2024, county='fresno', workers=1)
        assert guardian.toxic_emissions.filter(year=2024).count() > 10
        score = stats.valley_totals('cancer_weight')[2024]
        assert abs(score - 7595) <= 1, score
