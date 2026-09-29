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
