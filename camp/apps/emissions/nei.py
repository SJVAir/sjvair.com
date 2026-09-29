"""
EPA's National Emissions Inventory (NEI) at the county level, for what
CARB's own county inventory (CEPAM) doesn't publish: ammonia. Two data
summaries per NEI year, read straight out of their zips (the nonpoint CSV is
2.8 GB unpacked; nothing here writes it to disk):

- county x EPA sector, all pollutants: every county's total by sector;
- nonpoint county x SCC: the livestock-waste sector split by animal type
  (SCC level 3: "Dairy Cattle Waste", "Beef cattle waste", ...).

Only NH3 rows for the covered counties are kept. County FIPS codes join to
the county Regions' external_id (all eight). Estimates, not measurements.
"""
import csv
import io
import tempfile
import zipfile
from dataclasses import dataclass

import requests
from django.db import transaction

from camp.apps.emissions import stats
from camp.apps.emissions.models import CountyNEI, SourceImport
from camp.apps.regions.models import Region

SOURCE = 'nei'
POLLUTANT = 'NH3'
LBS_PER_TON = 2000.0
SECTOR_URL = 'https://gaftp.epa.gov/air/nei/2023/data_summaries/eis_report_38706_county_Sector_allpolls_28aug26.zip'
NONPOINT_URL = 'https://gaftp.epa.gov/air/nei/2023/data_summaries/2023nei_nonpoint_28aug2026.zip'
# NEI year -> (county x sector zip, nonpoint county x SCC zip). Add a row per release.
URLS = {2023: (SECTOR_URL, NONPOINT_URL)}
# EPA's sector names as the files spell them (Step 2 checks them against the samples).
LIVESTOCK_SECTOR = 'Agriculture - Livestock Waste'
FERTILIZER_SECTOR = 'Agriculture - Fertilizer Application'
DAIRY_SUBSECTOR = 'Dairy Cattle Waste'
# Each logical column's accepted header spellings, lowercased (the header is the contract).
SECTOR_COLUMNS = {
    'fips': ('fips code', 'state and county fips code', 'fips'),
    'sector': ('sector', 'eis sector'),
    'pollutant': ('pollutant code',),
    'tons': ('total emissions',),
    'uom': ('emissions uom', 'uom'),
}
NONPOINT_COLUMNS = {
    'fips': ('fips code', 'state and county fips code', 'fips'),
    'level3': ('scc level three', 'scc level 3', 'scc level-3'),
    'pollutant': ('pollutant code',),
    'tons': ('total emissions',),
    'uom': ('emissions uom', 'uom'),
}
NONPOINT_OPTIONAL = {'sector': ('sector', 'eis sector')}
CACHE_TIMEOUT = stats.CACHE_TIMEOUT


class NEIFormatError(ValueError):
    """The zip isn't the NEI layout this importer knows: no CSV, or a column is missing."""


def download(url):
    """Fetch a zip to a temp file and return its path (the caller unlinks it). The one network call here."""
    response = requests.get(url, timeout=1800, stream=True)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
    return tmp.name


def county_fips():
    """{5-digit county FIPS: county Region} for the covered counties (external_id is the FIPS)."""
    return {str(region.external_id).zfill(5): region for region in Region.objects.counties()}


def _resolve(fieldnames, columns, optional=None):
    """{logical name: real header} for `columns` (required) and `optional`; raises NEIFormatError on a missing required one."""
    lowered = {(name or '').strip().lower(): name for name in fieldnames or []}
    mapping = {}
    for key, candidates in columns.items():
        real = next((lowered[c] for c in candidates if c in lowered), None)
        if real is None:
            raise NEIFormatError(f"No {key} column ({' / '.join(candidates)}) in {list(lowered)}.")
        mapping[key] = real
    for key, candidates in (optional or {}).items():
        real = next((lowered[c] for c in candidates if c in lowered), None)
        if real is not None:
            mapping[key] = real
    return mapping


def _rows(zip_path, columns, optional=None):
    """Streams the zip's first CSV row by row as {logical name: value}; never extracts."""
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith('.csv')]
        if not names:
            raise NEIFormatError(f'{zip_path} has no CSV member.')
        with archive.open(names[0]) as member:
            reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', errors='replace', newline=''))
            mapping = _resolve(reader.fieldnames, columns, optional)
            for row in reader:
                yield {key: (row.get(real) or '').strip() for key, real in mapping.items()}


def _tons(row):
    """The row's emissions as tons/yr (the files say TON; a LB row is converted)."""
    try:
        value = float(row['tons'])
    except (TypeError, ValueError):
        return None
    if row.get('uom', '').upper().startswith('LB'):
        value /= LBS_PER_TON
    return value


def read_sector(zip_path, fips):
    """[{'fips', 'sector', 'tons'}] for NH3 in the given county FIPS codes, summed per (fips, sector)."""
    sums = {}
    for row in _rows(zip_path, SECTOR_COLUMNS):
        code = row['fips'].zfill(5)
        if row['pollutant'].upper() != POLLUTANT or code not in fips:
            continue
        tons = _tons(row)
        if tons is None:
            continue
        key = (code, row['sector'])
        sums[key] = sums.get(key, 0.0) + tons
    return [{'fips': code, 'sector': sector, 'tons': tons} for (code, sector), tons in sorted(sums.items())]


def read_nonpoint(zip_path, fips):
    """
    [{'fips', 'level3', 'tons'}] for NH3 from livestock waste in the given
    counties, summed per (fips, SCC level 3): the sector column when the
    file has one, else level-3 names ending in "waste".
    """
    sums = {}
    for row in _rows(zip_path, NONPOINT_COLUMNS, NONPOINT_OPTIONAL):
        code = row['fips'].zfill(5)
        if row['pollutant'].upper() != POLLUTANT or code not in fips:
            continue
        if 'sector' in row:
            livestock = row['sector'] == LIVESTOCK_SECTOR
        else:
            livestock = row['level3'].lower().endswith('waste')
        if not livestock:
            continue
        tons = _tons(row)
        if tons is None:
            continue
        key = (code, row['level3'])
        sums[key] = sums.get(key, 0.0) + tons
    return [{'fips': code, 'level3': level3, 'tons': tons} for (code, level3), tons in sorted(sums.items())]


@dataclass
class Report:
    year: int
    sector_rows: int = 0
    livestock_rows: int = 0
    counties: int = 0
    total_tons: float = 0.0

    def lines(self):
        return [
            f'NEI {self.year}: {self.sector_rows:,} county x sector rows and {self.livestock_rows:,} livestock rows for {self.counties} counties.',
            f'Valley {POLLUTANT}: {self.total_tons:,.0f} tons/yr.',
        ]


def apply(year, sector_rows, nonpoint_rows):
    """
    Replace the year's CountyNEI rows with the files' (one transaction),
    stamp SourceImport('nei', version=year), and orphan the cached
    explorer aggregates (the NEI bar is keyed under stats.prefix()).
    """
    counties = county_fips()
    report = Report(year=year)
    with transaction.atomic():
        CountyNEI.objects.filter(year=year, pollutant=POLLUTANT).delete()
        rows = []
        seen = set()
        for row in sector_rows:
            county = counties.get(row['fips'])
            if county is None:
                continue
            seen.add(county.pk)
            rows.append(CountyNEI(county=county, year=year, pollutant=POLLUTANT, sector=row['sector'], subsector='', tons=row['tons']))
            report.total_tons += row['tons']
        report.sector_rows = len(rows)
        for row in nonpoint_rows:
            county = counties.get(row['fips'])
            if county is None:
                continue
            rows.append(CountyNEI(county=county, year=year, pollutant=POLLUTANT, sector=LIVESTOCK_SECTOR, subsector=row['level3'], tons=row['tons']))
        report.livestock_rows = len(rows) - report.sector_rows
        report.counties = len(seen)
        CountyNEI.objects.bulk_create(rows, batch_size=1000)
        SourceImport.objects.create(
            source=SOURCE, version=str(year),
            notes={'sector_rows': report.sector_rows, 'livestock_rows': report.livestock_rows, 'counties': report.counties},
        )
    stats.clear_caches()
    return report


# (The read side, `latest_year`, `context` and `dairy_tile`, is added in Task 3; leave room after `apply`.)
