from unittest.mock import MagicMock, patch

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import cepam
from camp.apps.emissions.models import CountyInventory
from camp.apps.regions.models import Region

HEADER = '"DATA_SOURCE","YEAR","AREA","SEASON","EMISSION_TYPE","SRC_TYPE","EIC","EICSUMN","EICSOUN","EICMATN","EICSUBN","TOG","ROG","COT","NOX","SOX","PM","PM10","PM2_5"\n'
ROWS = (
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","STATIONARY"," 010-005-0110-0000","ELECTRIC UTILITIES","BOILERS","NATURAL GAS","SUB-CATEGORY UNSPECIFIED",.1,.2,.3,.4,.5,.6,.7,.8\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","AREAWIDE"," 620-614-5400-0000","FARMING OPERATIONS","LIVESTOCK WASTE","DAIRY CATTLE","SUB-CATEGORY UNSPECIFIED",1,2,,,,.5,.4,.1\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","MOBILE"," 723-723-1110-0000","HEAVY HEAVY DUTY DIESEL TRUCKS (HHDDT)","HHDDT","DIESEL","SUB-CATEGORY UNSPECIFIED",.3,.3,1,10,.01,.2,.2,.19\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","NATURAL+UNPLANNED FIRE EVENT"," 910-910-0000-0000","WILDFIRES","WILDFIRES","ALL VEGETATION","SUB-CATEGORY UNSPECIFIED",5,4,3,2,1,1,1,1\n'
    ',,,,,,,,,,,,,,,,,,\n'
    '\n\n'
)
CSV = HEADER + ROWS


class ParseTests(TestCase):
    fixtures = ['regions.yaml']

    def test_parses_rows_and_skips_blank_eics(self):
        county = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        rows = cepam.parse(CSV, county, 2017)
        assert len(rows) == 4
        stationary = rows[0]
        assert stationary.county == county
        assert stationary.year == 2017
        assert stationary.inventory == '2019V104ADJ'
        assert stationary.source_type == CountyInventory.SourceType.STATIONARY
        assert stationary.eic == '010-005-0110-0000'
        assert stationary.summary_name == 'ELECTRIC UTILITIES'
        assert stationary.nox == 0.4
        assert stationary.pm25 == 0.8
        assert [row.source_type for row in rows] == ['stationary', 'areawide', 'mobile', 'natural']
        assert rows[1].nox is None

    def test_unknown_source_type_is_an_error(self):
        county = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        bad = HEADER + ROWS.splitlines()[0].replace('"STATIONARY"', '"ORBITAL"') + '\n'
        with pytest.raises(ValueError, match='ORBITAL'):
            cepam.parse(bad, county, 2017)


class ImportCepamTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.fresno.metadata['ca_county_code'] = '10'
        self.fresno.save(update_fields=['metadata'])

    def run_import(self, text=CSV, year='2017', urls=None):
        def get(url, params=None, **kwargs):
            if urls is not None:
                urls.append(params)
            mock = MagicMock()
            mock.text = text
            mock.raise_for_status.return_value = None
            return mock
        with patch('camp.apps.emissions.cepam.requests.get', side_effect=get):
            call_command('import_cepam', year=year, county='fresno')

    def test_imports_and_replaces_idempotently(self):
        self.run_import()
        self.run_import()
        assert CountyInventory.objects.filter(county=self.fresno, year=2017).count() == 4

    def test_requests_whole_county_by_carb_number(self):
        params = []
        self.run_import(urls=params)
        assert params[0]['F_CO'] == 10
        assert params[0]['F_YR'] == 2017
        assert params[0]['F_AREA'] == 'CO'
        assert params[0]['SP'] == cepam.INVENTORY

    def test_year_range(self):
        self.run_import(year='2016-2017')
        assert set(CountyInventory.objects.values_list('year', flat=True)) == {2016, 2017}

    def test_empty_response_keeps_existing_rows(self):
        self.run_import()
        self.run_import(text=HEADER)
        assert CountyInventory.objects.count() == 4

    def test_bad_year_range_is_an_error(self):
        with pytest.raises(CommandError):
            self.run_import(year='2024-2010')
