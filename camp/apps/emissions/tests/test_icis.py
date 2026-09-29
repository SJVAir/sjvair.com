import csv
import io
import os
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.db import models
from django.test import TestCase

from camp.apps.emissions import icis
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility, SourceImport

DATA = Path(__file__).parent / 'data' / 'icis-air'

# TEST PLANT is Fresno (FIPS 019, CARB 10), SJU, facid 1; TEST GAS STATION is
# Kern (029, CARB 15), SJU, facid 2; TEST CEMENT is Kern, EKAPCD (KER), facid 2.
PLANT = 'CASJV00006019C0001'
STATION = 'CASJV00006029S0002'
EKAPCD = 'CAKCA00000000000123'
NOWHERE = 'CASJV00006037S0001'  # Los Angeles County: not covered

FACILITIES = [
    {'PGM_SYS_ID': PLANT, 'REGISTRY_ID': '110000000001', 'FACILITY_NAME': 'TEST PLANT INC', 'STREET_ADDRESS': '123 MAIN ST',
     'CITY': 'FRESNO', 'COUNTY_NAME': 'FRESNO', 'STATE': 'CA', 'ZIP_CODE': '93728', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'Unaddressed-Local', 'LOCAL_CONTROL_REGION_CODE': 'SJV'},
    {'PGM_SYS_ID': STATION, 'REGISTRY_ID': '110000000002', 'FACILITY_NAME': 'OLD OWNER GAS', 'STREET_ADDRESS': '456 OAK AVE',
     'CITY': 'BAKERSFIELD', 'COUNTY_NAME': 'KERN', 'STATE': 'CA', 'ZIP_CODE': '93301', 'AIR_POLLUTANT_CLASS_DESC': 'Synthetic Minor',
     'AIR_OPERATING_STATUS_DESC': 'Permanently Closed', 'CURRENT_HPV': 'No Violation Identified', 'LOCAL_CONTROL_REGION_CODE': 'SJV'},
    {'PGM_SYS_ID': EKAPCD, 'REGISTRY_ID': '110000000003', 'FACILITY_NAME': 'DESERT CEMENT', 'STREET_ADDRESS': '1 QUARRY RD',
     'CITY': 'MOJAVE', 'COUNTY_NAME': 'KERN', 'STATE': 'CA', 'ZIP_CODE': '93501', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'No Violation Identified', 'LOCAL_CONTROL_REGION_CODE': 'KCA'},
    {'PGM_SYS_ID': NOWHERE, 'REGISTRY_ID': '110000000004', 'FACILITY_NAME': 'LA PLANT', 'STREET_ADDRESS': '1 LA ST',
     'CITY': 'LOS ANGELES', 'COUNTY_NAME': 'LOS ANGELES', 'STATE': 'CA', 'ZIP_CODE': '90001', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'No Violation Identified', 'LOCAL_CONTROL_REGION_CODE': 'SC'},
]
INSPECTIONS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '9001', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Full Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'FCE On-Site', 'ACTUAL_END_DATE': '03/15/2024', 'PROGRAM_CODES': 'CAATVP', 'ACTIVITY_PURPOSE_DESC': ''},
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '9002', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Partial Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'PCE Off-Site', 'ACTUAL_END_DATE': '06/30/2018', 'PROGRAM_CODES': '', 'ACTIVITY_PURPOSE_DESC': ''},
    {'PGM_SYS_ID': NOWHERE, 'ACTIVITY_ID': '9003', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Full Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'FCE On-Site', 'ACTUAL_END_DATE': '01/01/2024', 'PROGRAM_CODES': '', 'ACTIVITY_PURPOSE_DESC': ''},
]
NOVS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '8001', 'ENF_IDENTIFIER': 'NOV-1', 'ACTIVITY_TYPE_DESC': 'Informal Enforcement Action',
     'STATE_EPA_FLAG': 'L', 'ENF_TYPE_DESC': 'Notice of Violation', 'ACHIEVED_DATE': '05/02/2023', 'OFFICIAL_FLG': 'Y'},
]
FORMALS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '7001', 'ENF_IDENTIFIER': 'CASE-1', 'ACTIVITY_TYPE_DESC': 'Formal Enforcement Action',
     'STATE_EPA_FLAG': 'L', 'ENF_TYPE_DESC': 'Administrative - Formal (Settlement)', 'SETTLEMENT_ENTERED_DATE': '06/30/2024', 'PENALTY_AMOUNT': '12500.50'},
    {'PGM_SYS_ID': STATION, 'ACTIVITY_ID': '7002', 'ENF_IDENTIFIER': 'CASE-2', 'ACTIVITY_TYPE_DESC': 'Formal Enforcement Action',
     'STATE_EPA_FLAG': 'S', 'ENF_TYPE_DESC': 'Administrative - Formal (Settlement)', 'SETTLEMENT_ENTERED_DATE': '02/01/2015', 'PENALTY_AMOUNT': ''},
]
HPVS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '6001', 'AGENCY_TYPE_DESC': 'Local', 'ENF_RESPONSE_POLICY_CODE': 'HPV',
     'PROGRAM_DESCS': 'Title V Permits', 'POLLUTANT_DESCS': 'Nitrogen oxides', 'EARLIEST_FRV_DETERM_DATE': '',
     'HPV_DAYZERO_DATE': '04/01/2024', 'HPV_RESOLVED_DATE': ''},
]
PROGRAMS = [
    {'PGM_SYS_ID': PLANT, 'PROGRAM_CODE': 'CAATVP', 'PROGRAM_DESC': 'Title V Permits', 'AIR_OPERATING_STATUS_DESC': 'Operating'},
    {'PGM_SYS_ID': STATION, 'PROGRAM_CODE': 'CAASIP', 'PROGRAM_DESC': 'State Implementation Plan', 'AIR_OPERATING_STATUS_DESC': 'Operating'},
]


def build_zip(directory, facilities=FACILITIES, inspections=INSPECTIONS, novs=NOVS, formals=FORMALS, hpvs=HPVS, programs=PROGRAMS):
    """An ICIS-AIR_downloads.zip stand-in with the six files we read, from row dicts (each file's header is its rows' keys)."""
    path = os.path.join(directory, 'ICIS-AIR_downloads.zip')
    tables = {
        'facilities': facilities, 'inspections': inspections, 'novs': novs,
        'formals': formals, 'hpvs': hpvs, 'programs': programs,
    }
    with zipfile.ZipFile(path, 'w') as archive:
        for key, rows in tables.items():
            # An empty table still needs its real header (EPA's file always has one), not just PGM_SYS_ID.
            fieldnames = list(rows[0].keys()) if rows else list(icis.COLUMNS[key])
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(icis.FILES[key], buffer.getvalue())
    return path


def real_sample_zip(directory):
    """The checked-in trimmed CSVs (real ICIS rows) zipped up."""
    path = os.path.join(directory, 'real.zip')
    with zipfile.ZipFile(path, 'w') as archive:
        for name in icis.FILES.values():
            archive.write(DATA / name, name)
    return path


class ParseTests(TestCase):
    def test_the_three_verified_ids(self):
        assert icis.parse_pgm_sys_id('CASJV00006029S3636') == (15, 'SJU', 3636)
        assert icis.parse_pgm_sys_id('CASJV00006029S0075') == (15, 'SJU', 75)
        assert icis.parse_pgm_sys_id('CASJV00006077N7365') == (39, 'SJU', 7365)
        assert icis.parse_pgm_sys_id('CASJV00006019C0001') == (10, 'SJU', 1)

    def test_other_ids_do_not_parse(self):
        for bad in ('CAKCA00000000000123', '0900000012345', 'CA0000123456', 'CASJV00006037S0001', 'CASJV00006029X0001', 'CASJV00006029S00AB', ''):
            assert icis.parse_pgm_sys_id(bad) is None, bad


class ReadTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_keeps_valley_rows_and_their_events_only(self):
        data = icis.read(build_zip(self.tmp.name))
        assert [row['PGM_SYS_ID'] for row in data['facilities']] == [PLANT, STATION, EKAPCD]
        assert [row['ACTIVITY_ID'] for row in data['inspections']] == ['9001', '9002']
        assert len(data['novs']) == 1 and len(data['formals']) == 2 and len(data['hpvs']) == 1
        assert data['title_v'] == {PLANT}

    def test_the_real_layout(self):
        # The checked-in files are trimmed from the real download: the headers are EPA's.
        data = icis.read(real_sample_zip(self.tmp.name))
        ids = {row['PGM_SYS_ID'] for row in data['facilities']}
        assert {'CASJV00006029S3636', 'CASJV00006029S0075', 'CASJV00006077N7365'} <= ids
        assert any(row['PGM_SYS_ID'].startswith('CAKCA') for row in data['facilities'])
        assert data['inspections'] and data['formals']
        for row in data['facilities']:
            assert row['COUNTY_NAME'].upper() in {'FRESNO', 'KERN', 'KINGS', 'MADERA', 'MERCED', 'SAN JOAQUIN', 'STANISLAUS', 'TULARE'}


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')

    def run_apply(self, **tables):
        return icis.apply(icis.read(build_zip(self.tmp.name, **tables)))

    def test_matches_parsed_ids_and_replaces_events(self):
        report = self.run_apply()
        plant = AirComplianceFacility.objects.get(pgm_sys_id=PLANT)
        assert plant.facility == self.plant and plant.match_method == 'parsed'
        assert plant.title_v is True and plant.pollutant_class == 'Major' and plant.hpv_status == 'unaddressed'
        assert plant.address == {'street': '123 MAIN ST', 'city': 'FRESNO', 'county': 'FRESNO', 'zip': '93728'}
        assert plant.reported_through == date(2024, 6, 30)
        kinds = dict(plant.events.values_list('kind').annotate(n=models.Count('pk')).values_list('kind', 'n'))
        assert kinds == {'inspection': 2, 'nov': 1, 'formal': 1, 'hpv': 1}
        formal = plant.events.get(kind='formal')
        assert formal.penalty == Decimal('12500.50') and formal.agency == 'L' and formal.external_id == '7001'
        assert formal.action_type == 'Administrative - Formal (Settlement)'
        hpv = plant.events.get(kind='hpv')
        assert (hpv.date, hpv.resolved, hpv.pollutant, hpv.program) == (date(2024, 4, 1), None, 'Nitrogen oxides', 'Title V Permits')
        assert hpv.description == 'High-priority violation'
        station = AirComplianceFacility.objects.get(pgm_sys_id=STATION)
        assert station.facility == self.station and station.title_v is False
        assert station.events.get().penalty is None and station.reported_through == date(2015, 2, 1)
        assert report.matched == 2 and report.unmatched == 1 and report.events == 6

    def test_ekapcd_and_epa_ids_stay_unmatched(self):
        self.run_apply()
        desert = AirComplianceFacility.objects.get(pgm_sys_id=EKAPCD)
        assert desert.facility is None and desert.match_method == ''
        assert not AirComplianceFacility.objects.filter(pgm_sys_id=NOWHERE).exists()

    def test_crosswalk_matches_manually(self):
        from unittest.mock import patch
        cement = Facility.objects.get(name='TEST CEMENT')
        with patch.dict(icis.CROSSWALK, {EKAPCD: (15, 'KER', 2)}):
            self.run_apply()
        desert = AirComplianceFacility.objects.get(pgm_sys_id=EKAPCD)
        assert desert.facility == cement and desert.match_method == 'manual'

    def test_rerun_replaces_events(self):
        self.run_apply()
        self.run_apply(novs=[], formals=[dict(FORMALS[0], PENALTY_AMOUNT='99')])
        plant = AirComplianceFacility.objects.get(pgm_sys_id=PLANT)
        assert AirComplianceFacility.objects.count() == 3
        assert not plant.events.filter(kind='nov').exists()
        assert plant.events.get(kind='formal').penalty == Decimal('99')
        assert plant.reported_through == date(2024, 6, 30)

    def test_source_import_stamp(self):
        self.run_apply()
        stamp = SourceImport.latest('icis-air')
        assert stamp.data_through == date(2024, 6, 30)
        assert stamp.notes['facilities'] == 3 and stamp.notes['matched'] == 2

    def test_bad_dates_are_skipped_not_fatal(self):
        self.run_apply(novs=[dict(NOVS[0], ACHIEVED_DATE='')])
        assert not AirComplianceFacility.objects.get(pgm_sys_id=PLANT).events.filter(kind='nov').exists()
