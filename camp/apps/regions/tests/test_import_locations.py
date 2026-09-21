import csv
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


def trimmed(path, keep, delimiter=','):
    """Copy a sample file, keeping only the rows whose first column is in `keep`."""
    with open(path, encoding='latin-1', newline='') as source:
        rows = list(csv.reader(source, delimiter=delimiter))
    handle = tempfile.NamedTemporaryFile('w', suffix='.txt', encoding='latin-1',
        newline='', delete=False)
    writer = csv.writer(handle, delimiter=delimiter, lineterminator='\n',
        quoting=csv.QUOTE_NONE if delimiter == '\t' else csv.QUOTE_MINIMAL)
    writer.writerow(rows[0])
    writer.writerows([row for row in rows[1:] if row[0] in keep])
    handle.close()
    return handle.name


class PublicSchoolImportTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.district = make_district('Orchard Unified', 'orchard-unified', '10621170000000')

    def test_imports_only_active_in_valley_schools(self):
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 5
        assert counts['updated'] == 0
        assert counts['removed'] == 0
        assert counts['skipped'] == 0
        assert set(Location.objects.values_list('name', flat=True)) == {
            'Orchard High',
            'Almond Elementary',
            'Blossom Academy',
            'Sagebrush Elementary',
            'Tumbleweed Middle',
        }

    def test_all_rows_are_public_schools_from_the_cde_public_source(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert Location.objects.exclude(type=Location.Type.PUBLIC_SCHOOL).count() == 0
        assert Location.objects.exclude(source='cde-public').count() == 0

    def test_sets_the_fields_from_the_file(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        school = Location.objects.get(external_id='10621176059453')

        assert school.name == 'Orchard High'
        assert school.address == '100 Almond Ave'
        assert school.city == 'Selma'
        assert school.zip == '93662-1000'
        assert round(school.point.y, 4) == 36.71
        assert round(school.point.x, 4) == -119.79
        assert school.metadata['grades'] == '9-12'
        assert school.metadata['charter'] is False
        assert school.imported_at is not None

    def test_resolves_county_and_district(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)

        school = Location.objects.get(external_id='10621176059453')
        assert school.county == Region.objects.get(pk=9001)
        assert school.district == self.district

        kern = Location.objects.get(external_id='15633216059455')
        assert kern.county == Region.objects.get(pk=9002)
        assert kern.district is None

    def test_rerun_updates_without_duplicating(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        counts = locations.import_source('cde-public', path=PUBLIC_PATH)

        assert counts['imported'] == 0
        assert counts['updated'] == 5
        assert counts['removed'] == 0
        assert Location.objects.count() == 5

    def test_rows_missing_from_the_source_are_removed(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(PUBLIC_PATH, {'10621176059453', '15633216059455'}, delimiter='\t')

        counts = locations.import_source('cde-public', path=path)

        assert counts['updated'] == 2
        assert counts['removed'] == 3
        assert set(Location.objects.values_list('external_id', flat=True)) == {
            '10621176059453', '15633216059455',
        }

    def test_an_empty_parse_removes_nothing(self):
        locations.import_source('cde-public', path=PUBLIC_PATH)
        path = trimmed(PUBLIC_PATH, set(), delimiter='\t')

        counts = locations.import_source('cde-public', path=path)

        assert counts['removed'] == 0
        assert Location.objects.count() == 5

    def test_locations_from_another_source_are_left_alone(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)
        locations.import_source('cde-public', path=PUBLIC_PATH)

        assert Location.objects.filter(source='cdss-ccl').count() == 3


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
        assert school.district == self.district
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

        assert counts['imported'] == 3
        assert set(Location.objects.values_list('name', flat=True)) == {
            'Little Sprouts Learning Center',
            'First Steps Infant Center',
            'Mesa Afterschool Club',
        }
        assert not Location.objects.filter(name='Ramirez Family Child Care').exists()
        assert not Location.objects.filter(name='Closed Kids Center').exists()

    def test_stores_capacity_and_type(self):
        locations.import_source('cdss-ccl', path=CCL_PATH)
        facility = Location.objects.get(external_id='100400001')

        assert facility.type == Location.Type.CHILD_CARE
        assert facility.metadata['capacity'] == 84
        assert facility.metadata['facility_type'] == 'DAY CARE CENTER'
        assert facility.county == Region.objects.get(pk=9001)

    def test_does_not_geocode_rows_that_carry_coordinates(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            counts = locations.import_source('cdss-ccl', path=CCL_PATH)

        assert geocode.call_count == 0
        assert counts['geocoded'] == 0


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

    def test_no_geocode_flag_is_passed_through(self):
        with mock.patch.object(locations, 'geocode_cached') as geocode:
            call_command('import_locations', source='cde-private', path=PRIVATE_PATH,
                no_geocode=True, stdout=StringIO())

        assert geocode.call_count == 0
        assert Location.objects.count() == 0
