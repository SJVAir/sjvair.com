import csv
import os
import tempfile

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
PUBLIC_PATH = str(DATA_DIR / 'pubschls-sample.txt')
PRIVATE_PATH = str(DATA_DIR / 'private-schools-sample.csv')
CCL_PATH = str(DATA_DIR / 'ccl-facilities-sample.csv')

# Inside the fixture's Fresno County square (-120.5 36.0 → -119.0 37.0),
# and inside the SELMA_SQUARE the test districts use.
FRESNO_POINT = (36.71, -119.79)


def trimmed(testcase, path, keep, delimiter=',', encoding='utf-8'):
    """Copy a sample file, keeping only the rows whose first column is in `keep`."""
    with open(path, encoding=encoding, newline='') as source:
        rows = list(csv.reader(source, delimiter=delimiter))
    handle = tempfile.NamedTemporaryFile('w', suffix='.txt', encoding=encoding,
        newline='', delete=False)
    writer = csv.writer(handle, delimiter=delimiter, lineterminator='\n',
        quoting=csv.QUOTE_NONE if delimiter == '\t' else csv.QUOTE_MINIMAL)
    writer.writerow(rows[0])
    writer.writerows([row for row in rows[1:] if row[0] in keep])
    handle.close()
    testcase.addCleanup(os.unlink, handle.name)
    return handle.name


class PublicSchoolImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.district = make_district('Orchard Unified', 'orchard-unified', '10621170000000')

    def test_imports_only_active_in_valley_schools(self):
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 6
        assert counts['updated'] == 0
        assert counts['removed'] == 0
        assert counts['skipped'] == 0
        assert set(Location.objects.values_list('name', flat=True)) == {
            'Orchard High',
            'Almond Elementary',
            'Cañada Elementary',
            'Blossom Academy',
            'Sagebrush Elementary',
            'Tumbleweed Middle',
        }

    def test_reads_the_latin_1_directory_without_mojibake(self):
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
        assert school.metadata['grades'] == '9-12'
        assert school.metadata['charter'] is False
        assert school.imported_at is not None

    def test_resolves_county_and_school_district(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        school = Location.objects.get(external_id='10621176059453')
        assert school.county == Region.objects.get(pk=9001)
        assert school.school_district == self.district

        kern = Location.objects.get(external_id='15633216059455')
        assert kern.county == Region.objects.get(pk=9002)
        assert kern.school_district is None

    def test_rerun_updates_without_duplicating(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 0
        assert counts['updated'] == 6
        assert counts['removed'] == 0
        assert Location.objects.count() == 6

    def test_rows_missing_from_the_source_are_removed(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(self, PUBLIC_PATH, {'10621176059453', '15633216059455'},
            delimiter='\t', encoding='latin-1')

        counts = locations.import_source('cde-public', path=path)

        assert counts['updated'] == 2
        assert counts['removed'] == 4
        assert set(Location.objects.values_list('external_id', flat=True)) == {
            '10621176059453', '15633216059455',
        }

    def test_an_empty_parse_removes_nothing(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(self, PUBLIC_PATH, set(), delimiter='\t', encoding='latin-1')

        counts = locations.import_source('cde-public', path=path)

        assert counts['removed'] == 0
        assert Location.objects.count() == 6

    def test_locations_from_another_source_are_left_alone(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert Location.objects.filter(source='cdss-ccl').count() == 4


class PrivateSchoolImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.district = make_district('Orchard Unified', 'orchard-unified', '10621170000000')
        self.point = Point(FRESNO_POINT[1], FRESNO_POINT[0], srid=4326)

    def test_geocodes_the_rows_without_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT) as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['imported'] == 3
        assert counts['geocoded'] == 3
        assert counts['skipped'] == 0
        assert geocode.call_count == 3
        assert 'Selma' in geocode.call_args_list[0].args[0]

    def test_skips_rows_without_an_enrollment(self):
        # The spec's filter is enrollment >= 6, and a blank doesn't clear it.
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)

        assert not Location.objects.filter(name='Quiet Hills Academy').exists()

    def test_a_failed_geocode_never_removes_a_row_thats_still_listed(self):
        partial = trimmed(self, PRIVATE_PATH, {'10621170123456'})
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=partial)
        existing = Location.objects.get(external_id='10621170123456')

        def geocode(address):
            return FRESNO_POINT if 'Willow' in address else None

        with mock.patch.object(locations, 'geocode_cached', side_effect=geocode) as patched:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        # The row already imported keeps its point, and isn't re-geocoded.
        assert 'Orange Ave' not in str(patched.call_args_list)
        assert counts['imported'] == 1
        assert counts['updated'] == 1
        assert counts['geocoded'] == 1
        assert counts['skipped'] == 1
        assert counts['removed'] == 0

        kept = Location.objects.get(external_id='10621170123456')
        assert kept.pk == existing.pk
        assert kept.point == existing.point
        assert Location.objects.count() == 2

    def test_skips_enrollment_under_six(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)

        assert not Location.objects.filter(name='Tiny Scholars Home School').exists()

    def test_stores_enrollment_and_grades(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)

        school = Location.objects.get(external_id='10621170123456')
        assert school.type == Location.Type.PRIVATE_SCHOOL
        assert school.metadata['enrollment'] == 148
        assert school.metadata['grade_low'] == 'K'
        assert school.metadata['grade_high'] == '8'
        assert school.school_district == self.district
        assert school.county == Region.objects.get(pk=9001)

    def test_no_geocode_skips_rows_without_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cde-private', path=PRIVATE_PATH, geocode=False)

        assert geocode.call_count == 0
        assert counts['imported'] == 0
        assert counts['geocoded'] == 0
        assert counts['skipped'] == 3
        assert Location.objects.count() == 0

    def test_a_failed_geocode_is_skipped(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=None):
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['imported'] == 0
        assert counts['skipped'] == 3

    def test_nothing_is_removed_when_every_row_is_skipped(self):
        with mock.patch.object(locations, 'geocode_cached', return_value=FRESNO_POINT):
            locations.import_source('cde-private', path=PRIVATE_PATH)

        with mock.patch.object(locations, 'geocode_cached', return_value=None):
            counts = locations.import_source('cde-private', path=PRIVATE_PATH)

        assert counts['removed'] == 0
        assert Location.objects.count() == 3


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
        'url': 'https://example.com/file.txt',
        'page_url': 'https://example.com/downloads',
    }

    def response(self, body, content_type='text/html; charset=utf-8'):
        response = mock.Mock()
        response.headers = {'Content-Type': content_type}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = iter([body])
        return response

    def read(self, config, response):
        with mock.patch.object(locations.requests, 'get', return_value=response):
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

    def test_html_wearing_a_plain_text_content_type_is_still_caught(self):
        response = self.response(b'\n<html><body>Blocked</body></html>', content_type='text/plain')

        with pytest.raises(locations.DownloadError):
            self.read(self.config, response)

    def test_a_real_file_downloads(self):
        response = self.response(b'CDSCode\tSchool\n1\tOrchard High\n', content_type='text/plain')

        assert self.read(self.config, response) == b'CDSCode\tSchool\n1\tOrchard High\n'

    def test_a_ckan_lookup_that_returns_a_web_page_is_a_failed_download(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError('not json')
        config = {'label': 'Test CKAN source', 'url': None,
            'ckan_dataset': 'nope', 'page_url': 'https://example.com/dataset'}

        with pytest.raises(locations.DownloadError):
            self.read(config, response)

    def test_a_ckan_csv_that_serves_html_is_a_failed_download(self):
        lookup = mock.Mock()
        lookup.raise_for_status.return_value = None
        lookup.json.return_value = {'result': {'resources': [
            {'format': 'CSV', 'url': 'https://example.com/facilities.csv'},
        ]}}
        page = self.response(b'<html>Blocked</html>')
        config = {'label': 'Test CKAN source', 'url': None,
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

        assert Location.objects.count() == 6
        output = stdout.getvalue()
        assert 'cde-public' in output
        assert 'imported=6' in output

    def test_requires_a_single_source_with_a_path(self):
        with pytest.raises(CommandError):
            call_command('import_locations', source='all', path=PUBLIC_PATH, stdout=StringIO())

    def test_all_skips_the_sources_that_cannot_download(self):
        stdout = StringIO()
        counts = {'imported': 0, 'updated': 0, 'removed': 0, 'geocoded': 0, 'skipped': 0}

        with mock.patch.object(locations, 'import_source', return_value=counts) as importer:
            call_command('import_locations', stdout=stdout)

        imported = [call.args[0] for call in importer.call_args_list]
        assert imported == ['cdss-ccl']
        output = stdout.getvalue()
        assert 'cde-public: no download available' in output
        assert 'cde-private: no download available' in output
        assert 'https://www.cde.ca.gov/ds/si/ds/pubschls.asp' in output

    def test_a_single_source_without_a_download_is_an_error(self):
        with pytest.raises(CommandError):
            call_command('import_locations', source='cde-private', stdout=StringIO())

    def test_a_download_failure_is_a_command_error(self):
        with mock.patch.object(locations, 'has_download', return_value=True):
            with mock.patch.object(locations, 'import_source',
                    side_effect=locations.DownloadError('boom')):
                with pytest.raises(CommandError):
                    call_command('import_locations', source='cde-public', stdout=StringIO())

    def test_a_file_that_parses_to_nothing_warns(self):
        stdout = StringIO()
        path = trimmed(self, PUBLIC_PATH, set(), delimiter='\t', encoding='latin-1')

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
        assert Location.objects.count() == 0
