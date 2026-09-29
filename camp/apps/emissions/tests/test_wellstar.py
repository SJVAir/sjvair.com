"""
data/wellstar-page.json is one real 12-feature page of CalGEM's WellSTAR
Wells layer (Kern and Fresno, Active/Idle/New), fetched 2026-09-29 with the
curl in the Phase 7 plan, Task 4 Step 2.
"""
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import wells
from camp.apps.emissions.importers import wellstar
from camp.apps.emissions.models import SourceImport, Well
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data'
SPUD_MS = int(datetime(2015, 3, 4, tzinfo=timezone.utc).timestamp() * 1000)


def feature(api, lnglat, county='Kern', status='Active', hpz='Not Within HPZ', **extra):
    attrs = {
        'API': api, 'LeaseName': 'KERN RIVER', 'WellNumber': api[-3:], 'WellDesignation': 'OG', 'WellStatus': status,
        'WellType': 'OG', 'WellTypeLabel': 'Oil & Gas', 'OperatorCode': 'A0123', 'OperatorName': 'TEST OIL LLC',
        'FieldName': 'Kern River', 'CountyName': county, 'Latitude': lnglat[1], 'Longitude': lnglat[0],
        'SpudDate': SPUD_MS, 'inHPZ': hpz, 'isDirectionallyDrilled': 'N', 'GISSource': 'CalGEM',
    }
    attrs.update(extra)
    return {'attributes': attrs}


FEATURES = [
    feature('0402900001', IN_KERN),
    feature('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), status='Idle', hpz='Verified HPZ', isDirectionallyDrilled='Y'),
    feature('0402900003', (IN_KERN[0] + 0.002, IN_KERN[1]), status='New', SpudDate=None),
    feature('0401900004', NEAR_PLANT, county='Fresno'),
    feature('0403700005', (-118.2, 34.0), county='Los Angeles'),        # not covered: skipped
    feature('0402900006', (0, 0)),                                        # no coordinates: skipped
    feature('0402900007', IN_KERN, status='Plugged'),                     # never requested; skipped if it appears
    feature('', IN_KERN),                                                 # no API: skipped
]


def paged(features, size):
    """A fetch_page stand-in serving `features` `size` at a time, the way the service pages."""
    def fetch_page(offset, counties=None):
        page = features[offset:offset + size]
        return {'features': page, 'exceededTransferLimit': offset + size < len(features)}
    return fetch_page


class ParseTests(TestCase):
    def test_dates_and_bools(self):
        assert wellstar.parse_date(SPUD_MS) == date(2015, 3, 4)
        assert wellstar.parse_date('03/04/2015') == date(2015, 3, 4)
        assert wellstar.parse_date('2015-03-04T00:00:00') == date(2015, 3, 4)
        assert wellstar.parse_date(None) is None and wellstar.parse_date('') is None and wellstar.parse_date('soon') is None
        assert wellstar.parse_bool('Y') and wellstar.parse_bool('Yes') and wellstar.parse_bool(True) and wellstar.parse_bool(1)
        assert not wellstar.parse_bool('N') and not wellstar.parse_bool(None) and not wellstar.parse_bool('')

    def test_parse_feature(self):
        row = wellstar.parse_feature(FEATURES[1])
        assert row['api'] == '0402900002' and row['status'] == 'Idle' and row['in_hpz'] == 'Verified HPZ'
        assert row['directional'] is True and row['spud_date'] == date(2015, 3, 4) and row['county_name'] == 'Kern'
        assert (row['point'].x, row['point'].y) == (IN_KERN[0] + 0.001, IN_KERN[1]) and row['point'].srid == 4326
        assert wellstar.parse_feature(FEATURES[2])['spud_date'] is None
        for bad in FEATURES[5:]:
            assert wellstar.parse_feature(bad) is None, bad
        assert wellstar.parse_feature(feature('1', IN_KERN, inHPZ='Something new'))['in_hpz'] == ''

    def test_where_and_params(self):
        text = wellstar.where()
        assert "CountyName IN ('Fresno', 'Kern'" in text and "WellStatus IN ('Active', 'Idle', 'New')" in text
        params = wellstar.params(5000)
        assert params['resultOffset'] == 5000 and params['orderByFields'] == 'API' and params['returnGeometry'] == 'false'
        assert params['outFields'].split(',') == list(wellstar.OUT_FIELDS)

    def test_the_real_page(self):
        page = json.loads((DATA / 'wellstar-page.json').read_text())
        rows = [wellstar.parse_feature(f) for f in page['features']]
        assert len(rows) >= 10 and all(rows)
        assert page.get('exceededTransferLimit') is True
        for row in rows:
            assert 8 <= len(row['api']) <= 14 and row['status'] in wellstar.STATUSES
            assert row['county_name'] in ('Kern', 'Fresno') and 34 < row['point'].y < 38
        assert any(row['spud_date'] for row in rows), 'no SpudDate parsed: check its encoding in the sample'
        assert any(row['in_hpz'] for row in rows), 'no inHPZ value recognised: check Well.HPZ against the sample'


class PagesTests(TestCase):
    def test_pages_follow_the_transfer_limit(self):
        with patch('camp.apps.emissions.importers.wellstar.fetch_page', side_effect=paged(FEATURES, 3)) as fetch:
            pages = list(wellstar.pages())
        assert [len(page) for page in pages] == [3, 3, 2]
        assert [c.args[0] for c in fetch.call_args_list] == [0, 3, 6]


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def test_creates_matches_counties_and_skips(self):
        report = wellstar.apply(FEATURES)
        assert Well.objects.count() == 4
        idle = Well.objects.get(api='0402900002')
        assert idle.county == self.kern and idle.status == 'Idle' and idle.in_hpz == Well.HPZ.VERIFIED and idle.directional
        assert idle.label == 'KERN RIVER 002' and idle.calgem_url.endswith('api=0402900002') and idle.sqid
        assert Well.objects.get(api='0401900004').county == self.fresno
        assert (report.fetched, report.created, report.skipped) == (8, 4, 4)
        stamp = SourceImport.latest('wellstar')
        assert stamp.notes['wells'] == 4

    def test_rerun_upserts_and_removes(self):
        wellstar.apply(FEATURES)
        before = wells.generation()
        pk = Well.objects.get(api='0402900001').pk
        # 0001 becomes idle, 0002 unchanged, 0003 and the Fresno well are gone (plugged since), 0008 is new.
        again = [feature('0402900001', IN_KERN, status='Idle'), FEATURES[1], feature('0402900008', IN_KERN)]
        report = wellstar.apply(again)
        assert set(Well.objects.values_list('api', flat=True)) == {'0402900001', '0402900002', '0402900008'}
        assert Well.objects.get(api='0402900001').pk == pk and Well.objects.get(api='0402900001').status == 'Idle'
        assert (report.created, report.updated, report.unchanged, report.deleted) == (1, 1, 1, 2)
        assert wells.generation() == before + 1

    def test_a_county_name_that_stops_matching_keeps_that_countys_wells(self):
        wellstar.apply(FEATURES)
        # CalGEM respells Fresno: its well no longer matches, so Fresno keeps it; Kern's 0003 is still removed.
        again = [FEATURES[0], FEATURES[1], feature('0401900004', NEAR_PLANT, county='FRESNO CO.')]
        report = wellstar.apply(again)
        assert set(Well.objects.values_list('api', flat=True)) == {'0402900001', '0402900002', '0401900004'}
        assert report.deleted == 1 and report.unknown_counties == ['FRESNO CO.']
        assert 'FRESNO CO.' in report.lines()[1]

    def test_a_duplicate_api_in_the_feed_is_written_once(self):
        wellstar.apply([FEATURES[0], FEATURES[0]])
        assert Well.objects.count() == 1


class CommandAndTaskTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_fetches_every_page(self):
        with patch('camp.apps.emissions.importers.wellstar.fetch_page', side_effect=paged(FEATURES, 5)):
            call_command('import_wells')
        assert Well.objects.count() == 4

    def test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'page.json')
            with open(path, 'w') as handle:
                json.dump({'features': FEATURES[:4]}, handle)
            call_command('import_wells', path=path)
        assert Well.objects.count() == 4

    def test_empty_feed_changes_nothing(self):
        wellstar.apply(FEATURES[:1])
        with patch('camp.apps.emissions.importers.wellstar.fetch_page', side_effect=paged([], 5)):
            with pytest.raises(CommandError, match='no wells'):
                call_command('import_wells')
        assert Well.objects.count() == 1
