"""
data/nei/sector.csv and nonpoint.csv are trimmed from EPA's real 2023 NEI
data summaries (the county x sector "allpolls" zip and the nonpoint zip),
streamed and filtered to the Valley's NH3 rows plus two decoys; see the
Phase 5 plan, Task 1 Step 2, for the exact command.
"""
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import nei, stats
from camp.apps.emissions.models import CountyNEI, SourceImport
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data' / 'nei'
FRESNO, KERN, LA = '06019', '06029', '06037'

SECTOR_HEADER = ['fips code', 'county', 'sector', 'pollutant code', 'total emissions', 'emissions uom']
SECTOR_ROWS = [
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, 'NH3', '9784', 'TON'],
    [FRESNO, 'Fresno', nei.FERTILIZER_SECTOR, 'NH3', '3806', 'TON'],
    [FRESNO, 'Fresno', 'Waste Disposal', 'NH3', '500', 'TON'],
    [FRESNO, 'Fresno', 'Fuel Comb - Electric Generation - Natural Gas', 'NH3', '200000', 'LB'],  # 100 tons
    [FRESNO, 'Fresno', 'Mobile - On-Road non-Diesel Light Duty Vehicles', 'NOX', '5000', 'TON'],  # not NH3
    [KERN, 'Kern', nei.LIVESTOCK_SECTOR, 'NH3', '7149', 'TON'],
    [KERN, 'Kern', nei.FERTILIZER_SECTOR, 'NH3', '10255', 'TON'],
    [LA, 'Los Angeles', nei.LIVESTOCK_SECTOR, 'NH3', '999', 'TON'],  # not covered
    [FRESNO, 'Fresno', 'Waste Disposal', 'NH3', '', 'TON'],  # blank: skipped
]
NONPOINT_HEADER = ['fips code', 'county', 'sector', 'scc', 'scc level three', 'pollutant code', 'total emissions', 'emissions uom']
NONPOINT_ROWS = [
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '4000', 'TON'],
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805018001', nei.DAIRY_SUBSECTOR, 'NH3', '70', 'TON'],  # a second SCC: summed
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805002000', 'Beef cattle waste', 'NH3', '5714', 'TON'],
    [FRESNO, 'Fresno', nei.FERTILIZER_SECTOR, '2801700001', 'Fertilizer Application', 'NH3', '3806', 'TON'],  # not livestock
    [KERN, 'Kern', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '3492', 'TON'],
    [LA, 'Los Angeles', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '1', 'TON'],
]


def build_zip(directory, name, header, rows):
    """A one-CSV zip like EPA's, from a header and rows."""
    path = os.path.join(directory, name)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name.replace('.zip', '.csv'), buffer.getvalue())
    return path


def zip_of(directory, csv_path):
    """One of the checked-in trimmed CSVs, zipped the way EPA ships it."""
    path = os.path.join(directory, csv_path.stem + '-real.zip')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.write(csv_path, csv_path.name)
    return path


class NEITestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.sector_zip = build_zip(self.tmp.name, 'sector.zip', SECTOR_HEADER, SECTOR_ROWS)
        self.nonpoint_zip = build_zip(self.tmp.name, 'nonpoint.zip', NONPOINT_HEADER, NONPOINT_ROWS)
        self.fips = set(nei.county_fips())


class ReadTests(NEITestCase):
    def test_county_fips(self):
        assert self.fips == {'06019', '06029', '06031', '06039', '06047', '06077', '06099', '06107'}
        assert nei.county_fips()['06019'] == self.fresno

    def test_sector_rows_filter_convert_and_sum(self):
        rows = nei.read_sector(self.sector_zip, self.fips)
        by_key = {(row['fips'], row['sector']): row['tons'] for row in rows}
        assert by_key[(FRESNO, nei.LIVESTOCK_SECTOR)] == 9784
        assert by_key[(FRESNO, 'Fuel Comb - Electric Generation - Natural Gas')] == 100  # LB -> tons
        assert by_key[(FRESNO, 'Waste Disposal')] == 500  # the blank row added nothing
        assert (KERN, nei.FERTILIZER_SECTOR) in by_key
        assert not any(fips == LA for fips, _ in by_key)
        assert not any('NOX' in sector for _, sector in by_key)

    def test_nonpoint_keeps_livestock_only_and_sums_sccs(self):
        rows = nei.read_nonpoint(self.nonpoint_zip, self.fips)
        by_key = {(row['fips'], row['level3']): row['tons'] for row in rows}
        assert by_key == {
            (FRESNO, nei.DAIRY_SUBSECTOR): 4070, (FRESNO, 'Beef cattle waste'): 5714, (KERN, nei.DAIRY_SUBSECTOR): 3492,
        }

    def test_nonpoint_without_a_sector_column_uses_the_level3_name(self):
        header = [name for name in NONPOINT_HEADER if name != 'sector']
        rows = [[value for name, value in zip(NONPOINT_HEADER, row) if name != 'sector'] for row in NONPOINT_ROWS]
        path = build_zip(self.tmp.name, 'nosector.zip', header, rows)
        by_key = {(row['fips'], row['level3']) for row in nei.read_nonpoint(path, self.fips)}
        assert by_key == {(FRESNO, nei.DAIRY_SUBSECTOR), (FRESNO, 'Beef cattle waste'), (KERN, nei.DAIRY_SUBSECTOR)}

    def test_missing_column_is_a_format_error(self):
        import pytest
        path = build_zip(self.tmp.name, 'bad.zip', ['fips code', 'sector', 'value'], [[FRESNO, 'x', '1']])
        with pytest.raises(nei.NEIFormatError, match='pollutant'):
            nei.read_sector(path, self.fips)

    def test_reads_from_the_zip_without_extracting(self):
        # Nothing but the zips may appear in the temp directory: the 2.8 GB CSV must never touch the disk.
        before = set(os.listdir(self.tmp.name))
        nei.read_sector(self.sector_zip, self.fips)
        nei.read_nonpoint(self.nonpoint_zip, self.fips)
        assert set(os.listdir(self.tmp.name)) == before

    def test_the_real_layout(self):
        # The checked-in files carry EPA's real headers and sector names.
        rows = nei.read_sector(zip_of(self.tmp.name, DATA / 'sector.csv'), self.fips)
        sectors = {row['sector'] for row in rows}
        assert nei.LIVESTOCK_SECTOR in sectors and nei.FERTILIZER_SECTOR in sectors
        assert {row['fips'] for row in rows} <= self.fips and len({row['fips'] for row in rows}) == 8
        livestock = nei.read_nonpoint(zip_of(self.tmp.name, DATA / 'nonpoint.csv'), self.fips)
        assert nei.DAIRY_SUBSECTOR in {row['level3'] for row in livestock}
        assert all(row['tons'] > 0 for row in livestock)


class ApplyTests(NEITestCase):
    def run_apply(self):
        return nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))

    def test_writes_sector_and_subsector_rows(self):
        report = self.run_apply()
        fresno = CountyNEI.objects.filter(county=self.fresno, year=2023)
        assert fresno.filter(subsector='').count() == 4
        assert fresno.get(sector=nei.LIVESTOCK_SECTOR, subsector=nei.DAIRY_SUBSECTOR).tons == 4070
        assert fresno.get(sector=nei.LIVESTOCK_SECTOR, subsector='Beef cattle waste').tons == 5714
        assert CountyNEI.objects.filter(county=self.kern, subsector='').count() == 2
        assert not CountyNEI.objects.exclude(county__in=[self.fresno, self.kern]).exists()
        assert (report.sector_rows, report.livestock_rows, report.counties) == (6, 3, 2)
        assert abs(report.total_tons - (9784 + 3806 + 500 + 100 + 7149 + 10255)) < 1e-6
        stamp = SourceImport.latest('nei')
        assert stamp.version == '2023' and stamp.notes['counties'] == 2

    def test_rerun_replaces_and_bumps_the_cache(self):
        self.run_apply()
        before = stats.generation()
        CountyNEI.objects.filter(subsector='Beef cattle waste').update(tons=1)
        self.run_apply()
        assert CountyNEI.objects.get(county=self.fresno, subsector='Beef cattle waste').tons == 5714
        assert CountyNEI.objects.filter(year=2023).count() == 9
        assert stats.generation() == before + 1


class CommandTests(NEITestCase):
    def test_paths(self):
        call_command('import_nei', year=2023, sector_path=self.sector_zip, nonpoint_path=self.nonpoint_zip)
        assert CountyNEI.objects.count() == 9

    def test_default_downloads_and_unlinks(self):
        with patch('camp.apps.emissions.nei.download', side_effect=[self.sector_zip, self.nonpoint_zip]) as download:
            call_command('import_nei', year=2023)
        assert [c.args[0] for c in download.call_args_list] == list(nei.URLS[2023])
        assert not os.path.exists(self.sector_zip) and not os.path.exists(self.nonpoint_zip)
        assert SourceImport.latest('nei') is not None

    def test_unknown_year_without_paths(self):
        import pytest
        from django.core.management.base import CommandError
        with pytest.raises(CommandError, match='No download URLs'):
            call_command('import_nei', year=2020)


class ReadSideTests(NEITestCase):
    def setUp(self):
        super().setUp()
        nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))
        cache.clear()

    def test_context_for_a_county(self):
        from camp.apps.emissions.tests.test_stats import scope
        context = nei.context(scope(pollutant='nh3', county='fresno'))
        assert context['year'] == 2023 and context['total'] == 9784 + 3806 + 500 + 100
        parts = {part['key']: part for part in context['parts']}
        assert [part['key'] for part in context['parts']] == ['dairy', 'livestock', 'fertilizer', 'other']
        assert parts['dairy']['tons'] == 4070 and parts['livestock']['tons'] == 9784 - 4070
        assert parts['fertilizer']['tons'] == 3806 and parts['other']['tons'] == 600
        assert abs(sum(part['share'] for part in context['parts']) - 1) < 1e-9
        # TEST PLANT's 100 lbs (0.05 tons) of CEIDARS ammonia against the county's EPA total.
        assert context['facilities'] == 0.05 and abs(context['facility_share'] - 0.05 / 14190) < 1e-12
        assert context['counties'] == [self.fresno]

    def test_context_for_the_valley_and_its_absences(self):
        from camp.apps.emissions.tests.test_stats import scope
        everywhere = nei.context(scope(pollutant='nh3'))
        assert everywhere['total'] == 14190 + 7149 + 10255 and len(everywhere['counties']) == 8
        assert nei.context(scope(pollutant='nox', county='fresno')) is None
        assert nei.context(scope(pollutant='nh3', county='tulare')) is None  # no rows for Tulare
        CountyNEI.objects.all().delete()
        stats.clear_caches()
        assert nei.context(scope(pollutant='nh3')) is None and nei.latest_year() is None

    def test_dairy_tile(self):
        tile = nei.dairy_tile(self.fresno)
        assert tile == {'tons': 4070, 'share': 4070 / 14190, 'year': 2023}
        assert nei.dairy_tile(self.kern) == {'tons': 3492, 'share': 3492 / (7149 + 10255), 'year': 2023}
        assert nei.dairy_tile(Region.objects.get(type=Region.Type.COUNTY, slug='tulare')) is None


class NeiBarTests(NEITestCase):
    def setUp(self):
        super().setUp()
        nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))
        cache.clear()

    def test_county_page_shows_the_bar_for_ammonia_only(self):
        content = self.client.get(self.fresno.get_emissions_url(), {'pollutant': 'nh3', 'year': '2024'}).content.decode()
        assert 'nei-context' in content and 'Dairy cattle' in content and "EPA's 2023 National Emissions Inventory" in content
        assert '14,190' in content and 'about 0%' not in content  # the share is written with `percent`: '<1%'
        assert '<1%' in content or '&lt;1%' in content  # HTML-escaped in the rendered page
        assert 'CARB estimates all sources' not in content
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        assert 'nei-context' not in content

    def test_home_page_bar_and_a_county_without_rows(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:home'), {'pollutant': 'nh3'}).content.decode()
        assert 'nei-context' in content and 'these counties' in content
        tulare = Region.objects.get(type=Region.Type.COUNTY, slug='tulare')
        assert 'nei-context' not in self.client.get(tulare.get_emissions_url(), {'pollutant': 'nh3'}).content.decode()

    def test_about_page(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="ammonia">Ammonia</h2>' in content
        assert 'only 7 dairies report ammonia to CARB' in content and 'NEI 2023 loaded' in content
        assert 'National Emissions Inventory' in self.client.get('/about/integrations/').content.decode()
