import json
from collections import Counter
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import ghg, ghg_crosswalk, ghgrp, icis, stats
from camp.apps.emissions.models import Facility, GHGReport, SourceImport
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data'


def load(name):
    return json.loads((DATA / name).read_text())


# TEST PLANT: Fresno (10, 'SJU', 1), point (-119.787, 36.737), ZIP 93728 (a fixture ZIP Region).
# TEST GAS STATION: Kern (15, 'SJU', 2), ZIP 93301 (no fixture ZIP Region).
# TEST CEMENT: Eastern Kern (15, 'KER', 2), point (-118.17, 35.05).
NEAR_PLANT = Point(-119.790, 36.739, srid=4326)      # ~350 m from TEST PLANT
FAR_FROM_PLANT = Point(-119.72, 36.737, srid=4326)   # ~6 km east


class GHGTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        # Phase 2: only trusted points take part in the distance match.
        Facility.objects.update(point_source=Facility.PointSource.CENSUS)


def report(program='mrr', external_id='1', year=2024, **kwargs):
    values = dict(name='X', co2e=10000.0)
    values.update(kwargs)
    return GHGReport.objects.create(program=program, external_id=external_id, year=year, **values)


class NameKeyTests(TestCase):
    def test_key_drops_corporate_noise(self):
        assert ghg.name_key('Ardagh Glass Inc.') == 'ARDAGH GLASS'
        assert ghg.name_key('PG&E McDonald Island Underground Storage Station') == 'PG AND E MCDONALD ISLAND UNDERGROUND STORAGE STATION'
        assert ghg.name_key('The Test Plant, LLC (Fresno)') == 'TEST PLANT FRESNO'
        assert ghg.name_key('') == ''

    def test_similarity(self):
        assert ghg.similarity('Test Plant Inc', 'TEST PLANT') == 1.0
        assert ghg.similarity('Mt. Poso Cogeneration Company', 'Sycamore Cogeneration Co') < ghg.AUTO_RATIO


class ResolveTests(GHGTestCase):
    def test_frs_id_wins(self):
        facility, method = ghg.resolve('ghgrp', '1', name='UNRELATED NAME', frs_air_id='CASJV00006019C0001', point=FAR_FROM_PLANT)
        assert facility == self.plant and method == 'frs'

    def test_frs_id_for_an_unknown_facility_falls_through(self):
        facility, method = ghg.resolve('ghgrp', '1', name='Nothing Like It', frs_air_id='CASJV00006019C9999', point=FAR_FROM_PLANT)
        assert facility is None and method == ''
        # Eastern Kern ids don't parse; they fall through too.
        facility, method = ghg.resolve('ghgrp', '1', name='Test Cement', frs_air_id='CAKCA000000000002', point=Point(-118.17, 35.05, srid=4326))
        assert facility == self.cement and method == 'auto'

    def test_crosswalk_beats_auto_and_can_pin_none(self):
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 2), '8': None}, clear=True):
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.cement, 'crosswalk')
            assert ghg.resolve('mrr', '8', name='Test Plant', zipcode='93728') == (None, 'crosswalk')
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 999)}, clear=True):
            # A stale key (no such facility) is ignored, not fatal.
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.plant, 'auto')

    def test_auto_match_by_zip(self):
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728-1234') == (self.plant, 'auto')
        # Same ZIP, different name.
        assert ghg.resolve('mrr', '1', name='Fresno Cogeneration Partners', zipcode='93728') == (None, '')
        # Right name, other ZIP.
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93301') == (None, '')

    def test_auto_match_by_distance(self):
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (self.plant, 'auto')
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=FAR_FROM_PLANT) == (None, '')
        Facility.objects.filter(pk=self.plant.pk).update(point_source=Facility.PointSource.MAPTILER)
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (None, '')

    def test_auto_match_needs_a_clear_winner(self):
        # Multi-site companies reuse a name across CEIDARS facilities: two
        # equal candidates (1.0 and 1.0) is no match at all.
        twin = Facility.objects.create(
            county_code=10, air_district=self.plant.air_district, facid=77, name='TEST PLANT', sic_code=3221,
            address={'zipcode': '93728'}, point=Point(-119.788, 36.738, srid=4326), point_source=Facility.PointSource.CENSUS,
            county=self.fresno, zipcode=self.plant.zipcode,
        )
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (None, '')
        # 'TEST PLANT NORTH' scores 0.8 against 'Test Plant' (at the ratio floor)
        # and the original scores 1.0: a clear winner either way round.
        Facility.objects.filter(pk=twin.pk).update(name='TEST PLANT NORTH')
        twin.refresh_from_db()
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant North', zipcode='93728') == (twin, 'auto')


def envirofacts(responses):
    """A fetch_json stand-in: the first payload whose key is in the URL, else []."""
    def fetch(url):
        for needle, payload in responses.items():
            if needle in url:
                return payload
        return []
    return fetch


def ef_facility(facility_id, fips, name, lat, lng, frs_id='', zipcode='93728'):
    return {
        'facility_id': facility_id, 'latitude': lat, 'longitude': lng, 'city': 'FRESNO', 'zip': zipcode,
        'county_fips': fips, 'facility_name': name, 'naics_code': '327213', 'frs_id': frs_id,
        'reported_subparts': 'C', 'facility_types': 'Direct Emitter', 'year': 2023,
    }


def ef_gas(facility_id, gas_id, co2e):
    return {'facility_id': facility_id, 'year': 2023, 'sector_id': 8, 'subsector_id': 7, 'gas_id': gas_id, 'co2e_emission': co2e}


class GHGRPParseTests(TestCase):
    def test_gas_totals_and_figures(self):
        totals = ghgrp.gas_totals(load('ghgrp/emissions-1000005.json'))
        assert totals == {1: 71521.2, 2: 24.25, 3: 28.906}
        figures = ghgrp.figures(totals, 2023)
        assert round(figures['co2e'], 3) == 71574.356
        assert figures['co2e_biogenic'] is None
        assert round(figures['ch4'], 3) == 0.97 and round(figures['n2o'], 4) == 0.097
        # Two sector rows for one gas add up; biogenic CO2 stays out of co2e.
        rows = [ef_gas(1, 1, 100.0), ef_gas(1, 1, 50.0), ef_gas(1, 8, 900.0)]
        figures = ghgrp.figures(ghgrp.gas_totals(rows), 2023)
        assert figures == {'co2e': 150.0, 'co2e_biogenic': 900.0, 'ch4': None, 'n2o': None}
        # RY2024 onward uses AR5 GWPs.
        assert ghgrp.figures({2: 28.0, 3: 265.0}, 2024)['ch4'] == 1.0
        assert ghgrp.figures({2: 28.0, 3: 265.0}, 2024)['n2o'] == 1.0

    def test_frs_air_id(self):
        air_id = ghgrp.frs_air_id(load('ghgrp/frs-110000482022.json'))
        assert air_id == 'CASJV00006039C0801'
        assert icis.parse_pgm_sys_id(air_id) == (20, 'SJU', 801)
        assert ghgrp.frs_air_id([]) == ''

    def test_urls(self):
        assert ghgrp.facilities_url(2023, '06039').endswith('/pub_dim_facility/state/CA/year/2023/county_fips/06039/JSON')
        assert ghgrp.emissions_url(1000005, 2023).endswith('/pub_facts_sector_ghg_emission/facility_id/1000005/year/2023/JSON')
        assert ghgrp.frs_url('110000482022').endswith('/frs_program_facility/registry_id/110000482022/JSON')
        assert ghgrp.COUNTY_FIPS == ('06019', '06029', '06031', '06039', '06047', '06077', '06099', '06107')


class ImportGHGRPTests(GHGTestCase):
    def responses(self):
        return {
            'county_fips/06019': [
                # Matched through FRS despite the point being far and the name unrelated.
                ef_facility(501, '06019', 'Big Glass Co', 36.60, -119.60, frs_id='110000000501'),
                # Matched by name within 1 km.
                ef_facility(502, '06019', 'Test Plant', 36.739, -119.790),
                # Nothing to match: far from anything.
                ef_facility(503, '06019', 'Lonely Landfill', 36.60, -119.20),
                # Reported no emissions rows: skipped.
                ef_facility(504, '06019', 'Silent Site', 36.61, -119.21),
            ],
            'county_fips/06029': [
                ef_facility(601, '06029', 'Basin Gathering LLC', 35.30, -119.30, zipcode='93308'),
            ],
            'facility_id/501/': [ef_gas(501, 1, 1000.0), ef_gas(501, 2, 250.0), ef_gas(501, 8, 5.0)],
            'facility_id/502/': [ef_gas(502, 1, 2000.0)],
            'facility_id/503/': [ef_gas(503, 2, 500.0), ef_gas(503, 3, 298.0)],
            'facility_id/601/': [ef_gas(601, 1, 30000.0), ef_gas(601, 2, 25000.0)],
            'registry_id/110000000501': [
                {'registry_id': '110000000501', 'pgm_sys_acrnm': 'AIRS/AFS', 'pgm_sys_id': '06019C0001'},
                {'registry_id': '110000000501', 'pgm_sys_acrnm': 'AIR', 'pgm_sys_id': 'CASJV00006019C0001'},
            ],
        }

    def run_import(self, responses=None, **options):
        out = StringIO()
        with patch('camp.apps.emissions.ghgrp.fetch_json', side_effect=envirofacts(responses or self.responses())):
            call_command('import_ghgrp', year=2023, stdout=out, **options)
        return out.getvalue()

    def test_import_matches_figures_and_counties(self):
        out = self.run_import()
        rows = {r.external_id: r for r in GHGReport.objects.filter(program='ghgrp', year=2023)}
        assert set(rows) == {'501', '502', '503', '601'}
        assert rows['501'].facility == self.plant and rows['501'].match_method == 'frs'
        assert rows['501'].co2e == 1250.0 and rows['501'].co2e_biogenic == 5.0 and rows['501'].ch4 == 10.0 and rows['501'].n2o is None
        assert rows['501'].frs_id == '110000000501' and rows['501'].county == self.fresno
        assert rows['502'].facility == self.plant and rows['502'].match_method == 'auto'
        assert rows['503'].facility is None and rows['503'].match_method == '' and rows['503'].county == self.fresno
        assert rows['503'].n2o == 1.0 and rows['503'].point.x == -119.20
        assert rows['601'].county == self.kern and rows['601'].zipcode == '93308' and rows['601'].sector == 'Direct Emitter'
        assert 'Fresno County: 3 reporters (1 frs, 1 auto, 1 unmatched)' in out
        stamp = SourceImport.latest('ghgrp')
        assert stamp.version == '2023' and stamp.data_through == date(2023, 12, 31)
        assert stamp.notes['reporters'] == 4 and stamp.notes['matched'] == 2

    def test_idempotent_and_prunes(self):
        self.run_import()
        before = stats.generation()
        responses = self.responses()
        responses['county_fips/06019'] = responses['county_fips/06019'][:2]   # 503 and 504 gone upstream
        responses['facility_id/502/'] = [ef_gas(502, 1, 2500.0)]
        self.run_import(responses)
        assert stats.generation() == before + 1
        assert set(GHGReport.objects.values_list('external_id', flat=True)) == {'501', '502', '601'}
        assert GHGReport.objects.get(external_id='502').co2e == 2500.0
        assert SourceImport.objects.filter(source='ghgrp').count() == 2

    def test_one_county(self):
        self.run_import(county='kern')
        assert list(GHGReport.objects.values_list('external_id', flat=True)) == ['601']

    def test_a_failed_fetch_skips_the_facility(self):
        import requests
        responses = self.responses()
        def fetch(url):
            if 'facility_id/502/' in url:
                raise requests.ConnectionError('boom')
            return envirofacts(responses)(url)
        err = StringIO()
        with patch('camp.apps.emissions.ghgrp.fetch_json', side_effect=fetch):
            with pytest.raises(CommandError):
                call_command('import_ghgrp', year=2023, stdout=StringIO(), stderr=err)
        assert '502' in err.getvalue()
        assert set(GHGReport.objects.values_list('external_id', flat=True)) == {'501', '503', '601'}
