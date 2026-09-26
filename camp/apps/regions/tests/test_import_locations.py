import csv
import os
import tempfile

from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.regions import locations
from camp.apps.regions.models import Location, Region
from camp.apps.regions.tests.test_locations import make_district


DATA_DIR = Path(__file__).parent / 'data'
PUBLIC_PATH = str(DATA_DIR / 'cde-public-sample.csv')
PRIVATE_PATH = str(DATA_DIR / 'cde-private-sample.csv')
CCL_PATH = str(DATA_DIR / 'ccl-facilities-sample.csv')

# Inside the fixture's Fresno County square (-120.5 36.0 → -119.0 37.0),
# and inside the SELMA_SQUARE the test districts use.
FRESNO_POINT = (36.71, -119.79)


def trimmed(testcase, path, column, keep):
    """Copy a sample file, keeping only the rows whose `column` is in `keep`."""
    with open(path, encoding='utf-8-sig', newline='') as source:
        rows = list(csv.reader(source))
    index = rows[0].index(column)
    handle = tempfile.NamedTemporaryFile('w', suffix='.csv', encoding='utf-8-sig',
        newline='', delete=False)
    writer = csv.writer(handle, lineterminator='\n')
    writer.writerow(rows[0])
    writer.writerows([row for row in rows[1:] if row[index] in keep])
    handle.close()
    testcase.addCleanup(os.unlink, handle.name)
    return handle.name


class PublicSchoolImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        # The district whose boundary covers the sample's Selma points, and
        # the one the file names for Almond Elementary's address -- which
        # has no boundary here, so only the file can link a school to it.
        self.district = make_district('Orchard Unified', 'orchard-unified', '10621170000000')
        self.almond = make_district('Almond Elementary', 'almond-elementary',
            '10621250000000', geometry=None)

    def test_imports_only_active_in_valley_schools_with_a_campus(self):
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 5
        assert counts['updated'] == 0
        assert counts['removed'] == 0
        assert counts['skipped'] == 0
        assert set(Location.objects.values_list('name', flat=True)) == {
            'Orchard High',
            'Cañada Elementary',
            'Almond Elementary',
            'Blossom Academy',
            'Tumbleweed Middle',
        }

    def test_drops_closed_virtual_adult_and_out_of_valley_schools(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert not Location.objects.filter(name='Shuttered Elementary').exists()
        assert not Location.objects.filter(name='Orchard Online Academy').exists()
        assert not Location.objects.filter(name='Bayside High').exists()
        # Grade span AD-AD: adult education, no children on the campus.
        assert not Location.objects.filter(
            name='Orchard Adult Transition Program').exists()

    def test_reads_the_utf_8_export_without_mojibake(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        school = Location.objects.get(external_id='10621176059462')

        assert school.name == 'Cañada Elementary'
        assert school.address == '30 Cañada Ave'

    def test_all_rows_are_public_schools_from_the_cde_public_source(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert Location.objects.exclude(type=Location.Type.PUBLIC_SCHOOL).count() == 0
        assert Location.objects.exclude(source='cde-public').count() == 0

    def test_sets_the_fields_from_the_file(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        school = Location.objects.get(external_id='10621176059453')

        assert school.name == 'Orchard High'
        assert school.address == '100 Almond Ave'
        assert school.city_name == 'Selma'
        assert school.zip == '93662-1000'
        assert round(school.point.y, 4) == 36.71
        assert round(school.point.x, 4) == -119.79
        assert school.imported_at is not None

    def test_stores_the_metadata_the_spec_asks_for(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        metadata = Location.objects.get(external_id='10621176059453').metadata

        assert metadata['cds_code'] == '10621176059453'
        assert metadata['district_code'] == '1062117'
        assert metadata['district_name'] == 'Orchard Unified'
        assert metadata['geographic']['county'] == {'code': '10', 'name': 'Fresno'}
        assert metadata['geographic']['unified'] == {
            'code': '1062117', 'name': 'Orchard Unified'}
        assert metadata['geographic']['elementary'] == {'code': None, 'name': None}
        assert metadata['school_type'] == 'High'
        assert metadata['school_level'] == 'High'
        assert metadata['grade_low'] == '9'
        assert metadata['grade_high'] == '12'
        assert metadata['charter'] is False
        assert metadata['charter_number'] is None
        assert metadata['virtual'] == 'N'
        assert metadata['title_i'] == 'Y'
        assert metadata['assistance_status'] == 'No Status'
        assert metadata['locale'] == '41 - Rural, Fringe'
        assert metadata['website'] == 'http://www.orchardhigh.example'
        assert metadata['open_date'] == '2006-08-28'
        assert metadata['enrollment']['total'] == 1200
        assert metadata['enrollment']['by_grade']['12'] == 300
        assert metadata['enrollment']['by_grade']['tk'] is None
        assert metadata['demographics']['hispanic_latino'] == {'count': 840, 'pct': 70.0}
        assert metadata['subgroups']['english_learners'] == {'count': 300, 'pct': 25.0}
        assert metadata['subgroups']['free_reduced_meals']['pct'] == 85.0
        assert metadata['staff'] == {'total': 84, 'teacher': 60, 'admin': 5,
            'pupil_services': 7, 'other': 12}

    def test_a_charter_records_the_district_that_runs_it(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        charter = Location.objects.get(external_id='10101080109991')

        assert charter.metadata['charter'] is True
        assert charter.metadata['charter_number'] == '0746'
        assert charter.metadata['charter_funding'] == 'Directly funded'
        assert charter.metadata['district_name'] == 'Fresno County Office of Education'
        # Run by the county office, but it stands in Orchard Unified.
        assert charter.school_district == self.district

    def test_resolves_county_and_school_district(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        school = Location.objects.get(external_id='10621176059453')
        assert school.county == Region.objects.get(pk=9001)
        assert school.school_district == self.district

        kern = Location.objects.get(external_id='15633216059455')
        assert kern.county == Region.objects.get(pk=9002)
        assert kern.school_district is None

    def test_the_files_district_corrects_the_spatial_one(self):
        # Almond Elementary's point is inside Orchard Unified's boundary,
        # but the file puts its address in the Almond Elementary district.
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['district_corrected'] == 1
        assert Location.objects.get(
            external_id='10621256059470').school_district == self.almond

    def test_the_files_district_fills_in_where_the_point_is_outside_them_all(self):
        # Tumbleweed Middle's point is in no district boundary at all.
        tumbleweed = make_district('Tumbleweed Union', 'tumbleweed-union',
            '15633210000000', geometry=None)

        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['district_filled_in'] == 1
        assert counts['district_corrected'] == 1
        assert Location.objects.get(
            external_id='15633216059455').school_district == tumbleweed

    def test_a_district_the_file_names_but_we_dont_have_is_counted_apart(self):
        self.almond.delete()

        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['district_corrected'] == 0
        assert counts['district_filled_in'] == 0
        # Almond Elementary's district and Tumbleweed Union's, neither of
        # which has a Region here.
        assert counts['district_unknown'] == 2
        assert Location.objects.get(
            external_id='10621256059470').school_district == self.district

    def test_rerun_updates_without_duplicating(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 0
        assert counts['updated'] == 5
        assert counts['removed'] == 0
        assert Location.objects.count() == 5

    def test_rows_missing_from_the_source_are_removed(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(self, PUBLIC_PATH, 'CDS Code',
            {'10621176059453', '15633216059455'})

        counts = locations.import_source('cde-public', path=path)

        assert counts['updated'] == 2
        assert counts['removed'] == 3
        assert set(Location.objects.values_list('external_id', flat=True)) == {
            '10621176059453', '15633216059455',
        }

    def test_an_empty_parse_removes_nothing(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(self, PUBLIC_PATH, 'CDS Code', set())

        counts = locations.import_source('cde-public', path=path)

        assert counts['removed'] == 0
        assert Location.objects.count() == 5

    def test_locations_from_another_source_are_left_alone(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert Location.objects.filter(source='cdss-ccl').count() == 4

    def test_does_not_geocode_rows_that_carry_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert geocode.call_count == 0
        assert counts['geocoded'] == 0


class PrivateSchoolImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.district = make_district('Orchard Unified', 'orchard-unified', '10621170000000')

    def test_imports_the_schools_in_the_valley_with_six_or_more_students(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['imported'] == 4
        assert counts['skipped'] == 0
        assert not Location.objects.filter(name='Tiny Scholars Home School').exists()

    def test_a_matched_row_uses_the_files_web_mercator_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH,
                geocode=False)
        school = Location.objects.get(external_id='10621170123456')

        # The file's X/Y is EPSG:3857; the stored point is WGS 84.
        assert school.point.srid == 4326
        assert round(school.point.y, 4) == 36.71
        assert round(school.point.x, 4) == -119.79
        assert geocode.call_count == 0
        assert counts['geocoded'] == 0

    def test_a_row_the_geocoder_didnt_match_is_geocoded_from_match_addr(self):
        with mock.patch.object(locations, 'geocode_cached',
                return_value=FRESNO_POINT) as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['geocoded'] == 2
        assert [call.args[0] for call in geocode.call_args_list] == [
            'Highway 99, Selma, California, 93662',
            '700 Rural Route 4, Selma, California, 93662',
        ]
        school = Location.objects.get(external_id='10621170123472')
        assert round(school.point.y, 4) == 36.71

    def test_a_row_without_a_street_address_still_geocodes_on_match_addr(self):
        # Rural Route Montessori filed no street address, so the only thing
        # to place it by is the address the geocoder matched.
        with mock.patch.object(locations, 'geocode_cached',
                return_value=FRESNO_POINT) as geocode:
            locations.import_source('cde-private', path=PRIVATE_PATH)

        school = Location.objects.get(external_id='10621170123498')
        assert school.address == ''
        assert round(school.point.y, 4) == 36.71
        assert '700 Rural Route 4, Selma, California, 93662' in [
            call.args[0] for call in geocode.call_args_list]

    def test_no_geocode_skips_the_rows_it_cannot_place(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH,
                geocode=False)

        assert geocode.call_count == 0
        assert counts['imported'] == 2
        assert counts['skipped'] == 2

    def test_a_failed_geocode_never_removes_a_row_thats_still_listed(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)
        existing = Location.objects.get(external_id='10621170123472')

        with mock.patch.object(locations, 'geocode_cached', return_value=None) as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        # The row already imported keeps its point, and isn't re-geocoded.
        assert geocode.call_count == 0
        assert counts['removed'] == 0
        assert counts['updated'] == 4
        kept = Location.objects.get(external_id='10621170123472')
        assert kept.pk == existing.pk
        assert kept.point == existing.point

    def test_stores_the_metadata_the_spec_asks_for(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)

        school = Location.objects.get(external_id='10621170123456')
        assert school.type == Location.Type.PRIVATE_SCHOOL
        assert school.name == 'Willow Grove Christian School'
        assert school.address == '12 Willow Way'
        assert school.city_name == 'Selma'
        assert school.zip == '93662'
        assert school.metadata == {
            'cds_code': '10621170123456',
            'district_name': 'Orchard Unified',
            'classification': 'Nondenominational',
            'school_type': 'Coeducational',
            'accommodations': 'Day Only',
            'grade_low': 'K',
            'grade_high': '8',
            'enrollment': {
                'total': 148,
                'by_grade': {
                    'kg': 18, '1': 17, '2': 16, '3': 18, '4': 19, '5': 15,
                    '6': 16, '7': 14, '8': 15, '9': None, '10': None,
                    '11': None, '12': None,
                },
            },
            'staff': {
                'full_time_teachers': 9,
                'part_time_teachers': 3,
                'administrators': 2,
                'other': 4,
            },
            'tax_exempt': True,
        }

    def test_resolves_county_and_school_district_spatially(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        school = Location.objects.get(external_id='10621170123456')
        assert school.county == Region.objects.get(pk=9001)
        assert school.school_district == self.district
        # No CDS cross-check for private schools: nothing to compare against.
        assert counts['district_corrected'] == 0
        assert counts['district_filled_in'] == 0
        assert counts['district_unknown'] == 0

    def test_rerun_updates_without_duplicating(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['imported'] == 0
        assert counts['updated'] == 4
        assert Location.objects.count() == 4


class ChildCareImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_imports_licensed_centers_only(self):
        counts = locations.import_source('cdss-ccl', path=CCL_PATH)

        assert counts['imported'] == 4
        assert set(Location.objects.values_list('name', flat=True)) == {
            'Little Sprouts Learning Center',
            'First Steps Infant Center',
            'Niños Felices Learning Center',
            'Mesa Afterschool Club',
        }
        # Not child care, not a center, not in the valley.
        assert not Location.objects.filter(name='Sunset Adult Day Program').exists()
        assert not Location.objects.filter(name='Orchard Foster Family Agency').exists()
        assert not Location.objects.filter(name='Riverbend Day Care Center').exists()

    def test_reads_the_utf_8_export_without_mojibake(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)

        assert Location.objects.get(external_id='100400006').name == 'Niños Felices Learning Center'

    def test_stores_capacity_and_type(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)
        facility = Location.objects.get(external_id='100400001')

        assert facility.type == Location.Type.CHILD_CARE
        assert facility.name == 'Little Sprouts Learning Center'
        assert facility.address == '55 Orchard Way'
        assert facility.city_name == 'Selma'
        assert facility.zip == '93662'
        assert round(facility.point.y, 4) == 36.715
        assert round(facility.point.x, 4) == -119.795
        assert facility.metadata['capacity'] == 104  # the day care center plus the infant center licensed at the same address
        assert facility.metadata['facility_type'] == 'DAY CARE CENTER'
        assert facility.metadata['status'] == '3'
        assert facility.metadata['client_served'] == '950'
        assert facility.county == Region.objects.get(pk=9001)

    def test_a_site_licensed_as_several_facilities_is_one_row(self):
        # Little Sprouts is a day care center and an infant center at one
        # address, under two facility numbers.
        locations.import_source('cdss-ccl', path=CCL_PATH)
        site = Location.objects.get(name='Little Sprouts Learning Center')
        assert site.external_id == '100400001'
        assert site.metadata['facility_type'] == 'DAY CARE CENTER'
        assert site.metadata['facility_types'] == ['DAY CARE CENTER', 'INFANT CENTER']
        assert site.metadata['facility_numbers'] == ['100400001', '100400009']
        assert site.metadata['capacity'] == 84 + 20

    def test_keeps_every_child_care_center_kind(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)

        assert set(Location.objects.values_list('metadata__facility_type', flat=True)) == {
            'DAY CARE CENTER',
            'INFANT CENTER',
            'SCHOOL-AGE DC CENTER',
            'SINGLE CHILD CARE CE',
        }

    def test_does_not_filter_on_the_numeric_status_code(self):
        # The export is the licensed layer; STATUS is a code, not a state.
        locations.import_source('cdss-ccl', path=CCL_PATH)

        assert Location.objects.filter(metadata__status='4').count() == 1

    def test_does_not_geocode_rows_that_carry_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cdss-ccl', path=CCL_PATH)

        assert geocode.call_count == 0
        assert counts['geocoded'] == 0


class DownloadGuardTests(TestCase):
    config = {
        'label': 'Test source',
        'ckan_dataset': 'test-source',
        'page_url': 'https://example.com/downloads',
    }

    def source_url(self):
        """Skip the CKAN lookup: these tests are about the download itself."""
        return mock.patch.object(locations, '_source_url',
            return_value='https://example.com/file.txt')

    def response(self, body, content_type='text/html; charset=utf-8', status_code=200):
        response = mock.Mock()
        response.status_code = status_code
        response.headers = {'Content-Type': content_type}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = iter([body])
        return response

    def read(self, config, response, resolve_url=True):
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(locations.requests, 'get', return_value=response))
            if resolve_url:
                stack.enter_context(self.source_url())
            with locations._open_source(config, None) as handle:
                return handle.read()

    def test_an_html_bot_wall_is_a_failed_download(self):
        response = self.response(b'<!DOCTYPE html><html><title>Block</title></html>')

        with pytest.raises(locations.DownloadError) as excinfo:
            self.read(self.config, response)

        message = str(excinfo.value)
        assert 'blocks server-side downloads' in message
        assert 'https://example.com/downloads' in message
        assert '--path' in message

    def test_a_package_without_a_csv_is_a_failed_download(self):
        package = mock.Mock()
        package.raise_for_status.return_value = None
        package.json.return_value = {'result': {'resources': [
            {'format': 'GeoJSON', 'url': 'https://example.com/file.geojson'},
        ]}}

        with mock.patch.object(locations.requests, 'get', return_value=package):
            with pytest.raises(locations.DownloadError) as excinfo:
                locations._source_url(self.config)

        message = str(excinfo.value)
        assert 'No download URL for Test source' in message
        assert 'https://example.com/downloads' in message and '--path' in message

    def test_a_source_without_a_dataset_says_to_pass_the_file(self):
        with mock.patch.object(locations.requests, 'get') as get:
            with pytest.raises(locations.DownloadError) as excinfo:
                locations._source_url({'label': 'Test source', 'page_url': 'https://example.com/downloads'})

        assert not get.called
        assert 'has no download' in str(excinfo.value) and '--path' in str(excinfo.value)

    def test_html_wearing_a_plain_text_content_type_is_still_caught(self):
        response = self.response(b'\n<html><body>Blocked</body></html>', content_type='text/plain')

        with pytest.raises(locations.DownloadError):
            self.read(self.config, response)

    def test_a_real_file_downloads(self):
        response = self.response(b'CDSCode\tSchool\n1\tOrchard High\n', content_type='text/plain')

        assert self.read(self.config, response) == b'CDSCode\tSchool\n1\tOrchard High\n'

    def test_an_empty_download_is_a_failed_download(self):
        response = self.response(b'', content_type='text/csv')

        with pytest.raises(locations.DownloadError) as excinfo:
            self.read(self.config, response)

        assert 'empty file' in str(excinfo.value)

    def test_an_export_still_being_generated_is_waited_out(self):
        pending = self.response(b'', content_type='application/json', status_code=202)
        ready = self.response(b'CDS Code,School Name\n1,Orchard High\n',
            content_type='text/csv')

        with self.source_url(), mock.patch.object(locations, 'time') as clock:
            with mock.patch.object(locations.requests, 'get',
                    side_effect=[pending, ready]) as get:
                with locations._open_source(self.config, None) as handle:
                    body = handle.read()

        assert get.call_count == 2
        assert clock.sleep.call_count == 1
        assert body == b'CDS Code,School Name\n1,Orchard High\n'

    def test_an_export_that_never_finishes_is_a_failed_download(self):
        pending = [self.response(b'', status_code=202)
            for _ in range(locations.DOWNLOAD_ATTEMPTS)]

        with self.source_url(), mock.patch.object(locations, 'time'):
            with mock.patch.object(locations.requests, 'get', side_effect=pending):
                with pytest.raises(locations.DownloadError) as excinfo:
                    with locations._open_source(self.config, None) as handle:
                        handle.read()

        assert 'still being generated' in str(excinfo.value)

    def test_a_ckan_lookup_that_returns_a_web_page_is_a_failed_download(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError('not json')
        config = {'label': 'Test CKAN source',
            'ckan_dataset': 'nope', 'page_url': 'https://example.com/dataset'}

        with pytest.raises(locations.DownloadError):
            self.read(config, response, resolve_url=False)

    def test_a_ckan_csv_that_serves_html_is_a_failed_download(self):
        lookup = mock.Mock()
        lookup.raise_for_status.return_value = None
        lookup.json.return_value = {'result': {'resources': [
            {'format': 'CSV', 'url': 'https://example.com/facilities.csv'},
        ]}}
        page = self.response(b'<html>Blocked</html>')
        config = {'label': 'Test CKAN source',
            'ckan_dataset': 'yep', 'page_url': 'https://example.com/dataset'}

        with mock.patch.object(locations.requests, 'get', side_effect=[lookup, page]):
            with pytest.raises(locations.DownloadError):
                with locations._open_source(config, None) as handle:
                    handle.read()


class GeocodeCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_resolves_once_and_caches_the_result(self):
        point = Point(-119.79, 36.71, srid=4326)
        with mock.patch.object(locations, 'resolve', return_value=point) as resolve:
            first = locations.geocode_cached('100 Almond Ave, Selma, CA 93662')
            second = locations.geocode_cached('100 Almond Ave, Selma, CA 93662')

        assert resolve.call_count == 1
        assert first == second
        assert first == (36.71, -119.79)

    def test_returns_none_for_an_empty_address(self):
        with mock.patch.object(locations, 'resolve') as resolve:
            assert locations.geocode_cached('   ') is None
        assert resolve.call_count == 0

    def test_returns_none_when_the_geocoder_finds_nothing(self):
        with mock.patch.object(locations, 'resolve', return_value=None):
            assert locations.geocode_cached('123 Nowhere Rd') is None


class ImportLocationsCommandTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_imports_one_source_from_a_path(self):
        stdout = StringIO()
        call_command('import_locations', source='cde-public', path=PUBLIC_PATH, stdout=stdout)

        assert Location.objects.count() == 5
        output = stdout.getvalue()
        assert 'cde-public' in output
        assert 'imported=5' in output

    def test_requires_a_single_source_with_a_path(self):
        with pytest.raises(CommandError):
            call_command('import_locations', source='all', path=PUBLIC_PATH, stdout=StringIO())

    def test_all_imports_every_source(self):
        stdout = StringIO()
        counts = {'imported': 1, 'updated': 0, 'removed': 0, 'geocoded': 0,
            'skipped': 0, 'district_corrected': 0, 'district_filled_in': 0,
            'district_unknown': 0}

        with mock.patch.object(locations, 'import_source', return_value=counts) as importer:
            call_command('import_locations', stdout=stdout)

        assert [call.args[0] for call in importer.call_args_list] == [
            'cde-public', 'cde-private', 'cdss-ccl']

    def test_reports_the_district_tallies_apart_from_the_counts(self):
        stdout = StringIO()
        make_district('Orchard Unified', 'orchard-unified', '10621170000000')
        make_district('Almond Elementary', 'almond-elementary', '10621250000000',
            geometry=None)

        call_command('import_locations', source='cde-public', path=PUBLIC_PATH,
            stdout=stdout)

        output = stdout.getvalue()
        assert 'districts -- corrected: 1, unknown district: 1' in output
        # Nothing was filled in, so that tally is left out entirely.
        assert 'filled in' not in output
        # The tallies are their own line, not part of the counts summary.
        assert 'district_corrected' not in output

    def test_a_download_failure_is_a_command_error(self):
        with mock.patch.object(locations, 'import_source',
                side_effect=locations.DownloadError('boom')):
            with pytest.raises(CommandError):
                call_command('import_locations', source='cde-public', stdout=StringIO())

    def test_a_file_that_parses_to_nothing_warns(self):
        stdout = StringIO()
        path = trimmed(self, PUBLIC_PATH, 'CDS Code', set())

        call_command('import_locations', source='cde-public', path=path, stdout=stdout)

        output = stdout.getvalue()
        assert 'no rows parsed' in output
        assert path in output
        assert 'imported=0' not in output

    def test_no_geocode_flag_is_passed_through(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            call_command('import_locations', source='cde-private', path=PRIVATE_PATH,
                no_geocode=True, stdout=StringIO())

        assert geocode.call_count == 0
        # Only the row the file couldn't place needed geocoding.
        assert Location.objects.count() == 2


class ImportSchoolsCommandTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_imports_the_districts_before_the_schools(self):
        calls = []

        def record(name, *args, **kwargs):
            calls.append((name, kwargs.get('source')))

        with mock.patch('camp.apps.regions.management.commands.import_schools.call_command',
                side_effect=record):
            call_command('import_schools', stdout=StringIO())

        assert calls == [
            ('import_school_districts', None),
            ('import_locations', 'cde-public'),
        ]

    def test_passes_the_path_and_geocode_options_through(self):
        recorded = {}

        def record(name, *args, **kwargs):
            recorded[name] = kwargs

        with mock.patch('camp.apps.regions.management.commands.import_schools.call_command',
                side_effect=record):
            call_command('import_schools', path=PUBLIC_PATH, no_geocode=True,
                stdout=StringIO())

        assert recorded['import_locations']['path'] == PUBLIC_PATH
        assert recorded['import_locations']['no_geocode'] is True
