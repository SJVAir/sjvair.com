"""
EPA's ICIS-Air bulk download (Clean Air Act compliance): the facilities the
air districts and EPA report on, their inspections, notices of violation,
formal actions and high-priority violations.

Only federally reportable sources are here (about 660 of the Valley's
11,000 permitted facilities). SJVAPCD's own id is embedded in the ICIS id:
`CA` + `SJV` + `0000` + 5-digit county FIPS + a region letter (S/C/N) + the
district facid, which is the CEIDARS facid. Eastern Kern and EPA-lead ids
don't encode ours (icis_crosswalk). The district's reporting runs a year or
more behind: every surface stamps "reported through" the newest event date.
"""
import csv
import io
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

from django.conf import settings
from django.db import transaction

from camp.apps.emissions.icis_crosswalk import CROSSWALK
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility, SourceImport
from camp.apps.regions.models import Region

URL = 'https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip'
SOURCE = 'icis-air'
FILES = {
    'facilities': 'ICIS-AIR_FACILITIES.csv',
    'inspections': 'ICIS-AIR_FCES_PCES.csv',
    'novs': 'ICIS-AIR_INFORMAL_ACTIONS.csv',
    'formals': 'ICIS-AIR_FORMAL_ACTIONS.csv',
    'hpvs': 'ICIS-AIR_VIOLATION_HISTORY.csv',
    'programs': 'ICIS-AIR_PROGRAMS.csv',
}
# The columns each file must have (the header is the contract; a renamed column fails in read()).
COLUMNS = {
    'facilities': ('PGM_SYS_ID', 'REGISTRY_ID', 'FACILITY_NAME', 'STREET_ADDRESS', 'CITY', 'COUNTY_NAME', 'STATE', 'ZIP_CODE',
                   'AIR_POLLUTANT_CLASS_DESC', 'AIR_OPERATING_STATUS_DESC', 'CURRENT_HPV', 'LOCAL_CONTROL_REGION_CODE'),
    'inspections': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ACTIVITY_TYPE_DESC', 'COMP_MONITOR_TYPE_DESC', 'ACTUAL_END_DATE', 'PROGRAM_CODES'),
    'novs': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ENF_TYPE_DESC', 'ACHIEVED_DATE'),
    'formals': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ENF_TYPE_DESC', 'SETTLEMENT_ENTERED_DATE', 'PENALTY_AMOUNT'),
    'hpvs': ('PGM_SYS_ID', 'ACTIVITY_ID', 'AGENCY_TYPE_DESC', 'ENF_RESPONSE_POLICY_CODE', 'PROGRAM_DESCS', 'POLLUTANT_DESCS',
             'EARLIEST_FRV_DETERM_DATE', 'HPV_DAYZERO_DATE', 'HPV_RESOLVED_DATE'),
    'programs': ('PGM_SYS_ID', 'PROGRAM_CODE', 'PROGRAM_DESC'),
}
# County FIPS (the 3 digits after the state's 06) -> CARB's county number.
FIPS_TO_CARB = {'019': 10, '029': 15, '031': 16, '039': 20, '047': 24, '077': 39, '099': 50, '107': 54}
SJVAPCD = 'SJU'
_SJV_ID = re.compile(r'^CASJV000(\d{5})([SCN])(\d{1,6})$')
# EPA isn't consistent across files: the action files use slashes, the
# inspection and violation-history files dashes (10-28-2022).
DATE_FORMATS = ('%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%d-%b-%y')
TITLE_V_CODE = 'CAATVP'


class ICISFormatError(ValueError):
    """The zip isn't the ICIS-Air layout this importer knows: a file or a column is missing."""


def parse_pgm_sys_id(pgm_sys_id):
    """(CARB county code, 'SJU', facid) for an SJVAPCD id in a covered county, else None."""
    match = _SJV_ID.match((pgm_sys_id or '').strip())
    if not match:
        return None
    fips, _, facid = match.groups()
    # fips is the full 5-digit FIPS code (06 state + 3-digit county); the county code map is keyed on the 3-digit tail.
    county_code = FIPS_TO_CARB.get(fips[-3:])
    if county_code is None:
        return None
    return county_code, SJVAPCD, int(facid)


def parse_date(value):
    value = (value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value):
    value = (value or '').strip().replace(',', '').replace('$', '')
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def agency_code(value):
    """'L', 'S' or 'E' from STATE_EPA_FLAG ('L') or AGENCY_TYPE_DESC ('Local', 'State', 'EPA'); '' when unknown."""
    letter = (value or '').strip()[:1].upper()
    return letter if letter in ('L', 'S', 'E') else ''


def download(url=URL):
    """Fetch the zip to a temp file and return its path (the caller unlinks it). The one network call here."""
    response = requests.get(url, timeout=600, stream=True)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
    return tmp.name


def _rows(archive, name, columns):
    try:
        member = archive.open(name)
    except KeyError:
        raise ICISFormatError(f'The zip has no {name}.')
    reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', errors='replace', newline=''))
    header = reader.fieldnames or []
    missing = [column for column in columns if column not in header]
    if missing:
        raise ICISFormatError(f"{name} has no {', '.join(missing)} column.")
    return reader


def read(zip_path):
    """
    {facilities, inspections, novs, formals, hpvs, title_v} from the zip,
    streamed row by row: the facilities in CA and a covered county, then each
    event file filtered to those facilities' ids. Nothing is unpacked to disk.
    """
    counties = {name.upper() for name in settings.SJVAIR_COUNTIES}
    data = {key: [] for key in ('facilities', 'inspections', 'novs', 'formals', 'hpvs')}
    with zipfile.ZipFile(zip_path) as archive:
        for row in _rows(archive, FILES['facilities'], COLUMNS['facilities']):
            if row['STATE'].strip().upper() != 'CA' or row['COUNTY_NAME'].strip().upper() not in counties:
                continue
            data['facilities'].append(row)
        ids = {row['PGM_SYS_ID'] for row in data['facilities']}
        for key in ('inspections', 'novs', 'formals', 'hpvs'):
            data[key] = [row for row in _rows(archive, FILES[key], COLUMNS[key]) if row['PGM_SYS_ID'] in ids]
        data['title_v'] = {
            row['PGM_SYS_ID'] for row in _rows(archive, FILES['programs'], COLUMNS['programs'])
            if row['PGM_SYS_ID'] in ids and (row['PROGRAM_CODE'].strip() == TITLE_V_CODE or 'TITLE V' in row['PROGRAM_DESC'].upper())
        }
    return data


@dataclass
class Report:
    facilities: int = 0
    matched: int = 0
    unmatched: int = 0
    events: int = 0
    skipped: int = 0
    data_through: object = None

    def lines(self):
        return [
            f'ICIS-Air facilities in the covered counties: {self.facilities:,} ({self.matched:,} matched to CEIDARS, {self.unmatched:,} not).',
            f'Events: {self.events:,} written, {self.skipped:,} skipped (no date). Reported through {self.data_through or "—"}.',
        ]


def _match(pgm_sys_id, districts):
    """(Facility | None, match_method) for an ICIS id: parsed from the id, else the crosswalk, else nothing."""
    parsed = parse_pgm_sys_id(pgm_sys_id)
    method = AirComplianceFacility.MatchMethod.PARSED
    if parsed is None:
        parsed = CROSSWALK.get(pgm_sys_id)
        method = AirComplianceFacility.MatchMethod.MANUAL
    if parsed is None:
        return None, ''
    county_code, district, facid = parsed
    if district not in districts:
        return None, ''
    facility = Facility.objects.filter(county_code=county_code, air_district=districts[district], facid=facid).first()
    return facility, (method if facility is not None else '')


def _event(icis_facility, kind, row):
    """A ComplianceEvent for a row of one of the four event files, or None when it has no usable date."""
    E = ComplianceEvent
    if kind == E.Kind.INSPECTION:
        when, agency = parse_date(row['ACTUAL_END_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['COMP_MONITOR_TYPE_DESC'].strip() or row['ACTIVITY_TYPE_DESC'].strip()
        extra = {'description': row['ACTIVITY_TYPE_DESC'].strip(), 'program': row['PROGRAM_CODES'].strip()[:40]}
    elif kind == E.Kind.NOV:
        when, agency = parse_date(row['ACHIEVED_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['ENF_TYPE_DESC'].strip()
        extra = {'description': action}
    elif kind == E.Kind.FORMAL:
        when, agency = parse_date(row['SETTLEMENT_ENTERED_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['ENF_TYPE_DESC'].strip()
        extra = {'description': action, 'penalty': parse_decimal(row['PENALTY_AMOUNT'])}
    else:
        when = parse_date(row['HPV_DAYZERO_DATE']) or parse_date(row['EARLIEST_FRV_DETERM_DATE'])
        agency = agency_code(row['AGENCY_TYPE_DESC'])
        policy = row['ENF_RESPONSE_POLICY_CODE'].strip().upper()
        action = 'High-priority violation' if 'HPV' in policy else 'Federally reportable violation'
        extra = {
            'description': action, 'program': row['PROGRAM_DESCS'].strip()[:40], 'pollutant': row['POLLUTANT_DESCS'].strip()[:40],
            'resolved': parse_date(row['HPV_RESOLVED_DATE']),
        }
    if when is None:
        return None
    return E(icis_facility=icis_facility, kind=kind, date=when, agency=agency, action_type=action[:80],
             external_id=row['ACTIVITY_ID'].strip()[:40], **extra)


def apply(data):
    """
    Upsert the facilities on pgm_sys_id (matching each to a CEIDARS facility),
    replace their events, set reported_through, and stamp SourceImport, in
    one transaction. Rows for facilities no longer in the file are left as they
    are (ICIS never drops a source; a closed one stays with its history).
    """
    report = Report(facilities=len(data['facilities']))
    districts = {region.external_id: region for region in Region.objects.filter(type=Region.Type.AIR_DISTRICT)}
    kinds = {'inspections': ComplianceEvent.Kind.INSPECTION, 'novs': ComplianceEvent.Kind.NOV,
             'formals': ComplianceEvent.Kind.FORMAL, 'hpvs': ComplianceEvent.Kind.HPV}
    with transaction.atomic():
        rows = {}
        for row in data['facilities']:
            pgm_sys_id = row['PGM_SYS_ID'].strip()
            facility, method = _match(pgm_sys_id, districts)
            values = {
                'facility': facility, 'match_method': method,
                'registry_id': row['REGISTRY_ID'].strip()[:12], 'name': row['FACILITY_NAME'].strip()[:128],
                'address': {'street': row['STREET_ADDRESS'].strip(), 'city': row['CITY'].strip(),
                            'county': row['COUNTY_NAME'].strip(), 'zip': row['ZIP_CODE'].strip()},
                'pollutant_class': row['AIR_POLLUTANT_CLASS_DESC'].strip()[:32],
                'operating_status': row['AIR_OPERATING_STATUS_DESC'].strip()[:40],
                'title_v': pgm_sys_id in data['title_v'],
                'current_hpv': row['CURRENT_HPV'].strip()[:40],
                'local_region': row['LOCAL_CONTROL_REGION_CODE'].strip()[:8],
            }
            rows[pgm_sys_id], _ = AirComplianceFacility.objects.update_or_create(pgm_sys_id=pgm_sys_id, defaults=values)
            report.matched += facility is not None
            report.unmatched += facility is None
        ComplianceEvent.objects.filter(icis_facility__in=rows.values()).delete()
        events, seen = [], set()
        for key, kind in kinds.items():
            for row in data[key]:
                icis_facility = rows.get(row['PGM_SYS_ID'].strip())
                if icis_facility is None:
                    continue
                event = _event(icis_facility, kind, row)
                if event is None:
                    report.skipped += 1
                    continue
                dedupe = (icis_facility.pk, kind, event.external_id)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                events.append(event)
        ComplianceEvent.objects.bulk_create(events, batch_size=2000)
        report.events = len(events)
        latest = defaultdict(lambda: None)
        for event in events:
            if latest[event.icis_facility_id] is None or event.date > latest[event.icis_facility_id]:
                latest[event.icis_facility_id] = event.date
        for icis_facility in rows.values():
            through = latest[icis_facility.pk]
            if icis_facility.reported_through != through:
                icis_facility.reported_through = through
                icis_facility.save(update_fields=['reported_through'])
        report.data_through = max((d for d in latest.values() if d), default=None)
        SourceImport.objects.create(
            source=SOURCE, data_through=report.data_through,
            notes={'facilities': report.facilities, 'matched': report.matched, 'events': report.events},
        )
    return report
