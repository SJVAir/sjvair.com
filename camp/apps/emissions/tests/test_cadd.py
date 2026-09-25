import io
import os
import tempfile
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import cadd, dairies
from camp.apps.emissions.models import Dairy, DairyHerd, Digester, SizeClass, herd_totals, size_class
from camp.apps.regions.models import Region

# The sheet names as CARB spells them: the herd sheet's ends in a space.
SHEETS = ('Facility General Information', 'Facility Herd Size ', 'Anaerobic Digesters')


def facility(cadd_id, county='Fresno', lat=36.7, lng=-119.8, city='Riverdale'):
    return [cadd_id, 200000 + cadd_id, f'Dairy {cadd_id}', lat, lng, f'{cadd_id} Dairy Rd', city, county, 93656, '5F']


def herd(cadd_id, year, milk=100, dry=20, old_heifers=10, young_heifers=10, old_calves=5, young_calves=5, beef=0, ref=1):
    return [cadd_id, year, milk, dry, old_heifers, young_heifers, old_calves, young_calves, beef, ref, ref, 1]


# A footnote row under the herds, as in CARB's file: no CADDID, one text cell.
FOOTNOTE = [None] * 9 + ['See the CADD documentation for reference codes.', None, None]


def write_workbook(path, facilities, herds=(), digesters=(), drop=None):
    """A CADD-shaped XLSX. `drop` = (sheet name, column) leaves that column out."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in zip(SHEETS, (facilities, herds, digesters)):
        columns = list(cadd.COLUMNS[name.strip()])
        keep = [i for i, column in enumerate(columns) if drop != (name.strip(), column)]
        sheet = workbook.create_sheet(name)
        sheet.append([columns[i] for i in keep])
        for row in rows:
            sheet.append([row[i] for i in keep])
    workbook.save(path)


class ImportCADDTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'cadd.xlsx')

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, facilities, herds=(), digesters=()):
        write_workbook(self.path, facilities, herds, digesters)
        out = io.StringIO()
        call_command('import_cadd', '--path', self.path, stdout=out)
        return out.getvalue()

    def test_keeps_the_valley_dairies(self):
        output = self.run_import(
            [facility(1), facility(2, 'Tulare', lat=36.2, lng=-119.3), facility(3, 'Riverside', lat=33.8, lng=-117.0)],
            [herd(1, 2023), herd(3, 2023), FOOTNOTE],
        )
        assert sorted(Dairy.objects.values_list('cadd_id', flat=True)) == [1, 2]
        dairy = Dairy.objects.get(cadd_id=1)
        assert dairy.county.slug == 'fresno' and dairy.county.type == Region.Type.COUNTY
        assert (dairy.point.x, dairy.point.y) == (-119.8, 36.7)
        assert dairy.address == {'street': '1 Dairy Rd', 'city': 'Riverdale', 'zipcode': '93656'}
        assert (dairy.place_id, dairy.water_board, dairy.cadd_version) == (200001, '5F', cadd.VERSION)
        # Dairy 3 is in Riverside: its herd isn't kept either.
        assert DairyHerd.objects.count() == 1
        assert 'Outside the covered counties: 1.' in output

    def test_city_is_normalized_against_city_and_place_regions(self):
        Region.objects.create(name='Hanford', slug='hanford', type=Region.Type.CITY, external_id='hanford')
        Region.objects.create(name='McFarland', slug='mcfarland', type=Region.Type.PLACE, external_id='mcfarland')
        self.run_import([
            facility(1, city='HANFORD'),
            facility(2, city='MCFARLAND'),
            facility(3, city='SOME PLACE'),
            facility(4, city=''),
        ])
        by_id = {dairy.cadd_id: dairy for dairy in Dairy.objects.all()}
        # Matched a Region's name (case-insensitively): use its canonical name.
        assert by_id[1].address['city'] == 'Hanford'
        assert by_id[2].address['city'] == 'McFarland'
        # No matching Region: a sensible title case.
        assert by_id[3].address['city'] == 'Some Place'
        # Blank stays blank.
        assert by_id[4].address['city'] == ''

    def test_city_lookup_prefers_city_over_place_on_a_name_collision(self):
        # The PLACE is created first (lower pk) so a naive row-order lookup
        # would pick it; the CITY must still win.
        Region.objects.create(name='SELMA', slug='selma-place', type=Region.Type.PLACE, external_id='selma-place')
        Region.objects.create(name='Selma', slug='selma-city', type=Region.Type.CITY, external_id='selma-city')
        self.run_import([facility(1, city='selma')])
        assert Dairy.objects.get(cadd_id=1).address['city'] == 'Selma'

    def test_city_fixes_applied_before_the_region_match(self):
        Region.objects.create(name='Visalia', slug='visalia', type=Region.Type.CITY, external_id='visalia')
        self.run_import([
            facility(1, city='VISLIA'),
            facility(2, city='vislia'),
            facility(3, city='Kern County'),
        ])
        by_id = {dairy.cadd_id: dairy for dairy in Dairy.objects.all()}
        assert by_id[1].address['city'] == 'Visalia'
        assert by_id[2].address['city'] == 'Visalia'
        # A non-city value: fixed to blank, which stays blank.
        assert by_id[3].address['city'] == ''

    def test_blank_and_nan_counts_are_unknown(self):
        self.run_import([facility(1)], [herd(1, 2023, dry=None, beef=None), herd(1, 2022, milk='NaN')])
        row = DairyHerd.objects.get(year=2023)
        assert row.dry_cows is None and row.beef_cattle is None
        # 100 milk cows (no dry cows known); 10 + 10 + 5 + 5 other cattle (no beef known).
        assert (row.mature_cows, row.other_cattle, row.size_class) == (100, 30, SizeClass.SMALL)
        assert row.milk_cows_ref_code == '1' and row.labeled_as_dairy is True
        earlier = DairyHerd.objects.get(year=2022)
        assert earlier.milk_cows is None and (earlier.mature_cows, earlier.other_cattle) == (20, 30)
        assert herd_totals({'milk_cows': 10, 'dry_cows': None, 'beef_cattle': 3}) == {
            'mature_cows': 10, 'other_cattle': 3, 'size_class': SizeClass.SMALL,
        }

    def test_size_class_computed_at_import(self):
        self.run_import([facility(1), facility(2), facility(3)], [
            herd(1, 2023, milk=650, dry=50),
            herd(2, 2023, milk=0, dry=0, old_heifers=0, young_heifers=0, old_calves=0, young_calves=0, beef=1200),
            herd(3, 2023, milk=0, dry=0, old_heifers=0, young_heifers=0, old_calves=0, young_calves=0),
        ])
        rows = {row.dairy.cadd_id: row for row in DairyHerd.objects.select_related('dairy')}
        assert (rows[1].mature_cows, rows[1].size_class) == (700, SizeClass.LARGE)
        # A beef-only site: no mature dairy cows, classed by its other cattle.
        assert (rows[2].mature_cows, rows[2].other_cattle, rows[2].size_class) == (0, 1200, SizeClass.LARGE)
        # No cattle at all: no class.
        assert (rows[3].mature_cows, rows[3].other_cattle, rows[3].size_class) == (0, 0, '')

    def test_rerun_replaces_herds_and_keeps_ids(self):
        digesters = [[1, 2018, 'NaN', 'DDRDP']]
        self.run_import([facility(1), facility(2)], [herd(1, 2023, milk=100), herd(2, 2023)], digesters)
        first = dict(Dairy.objects.values_list('cadd_id', 'pk'))
        output = self.run_import([facility(1), facility(2)], [herd(1, 2023, milk=300), herd(2, 2023)], digesters)
        assert dict(Dairy.objects.values_list('cadd_id', 'pk')) == first
        assert DairyHerd.objects.count() == 2 and Digester.objects.count() == 1
        assert DairyHerd.objects.get(dairy__cadd_id=1).milk_cows == 300
        assert 'Dairies: 0 added, 2 updated.' in output

    def test_digesters_operating_and_shut_down(self):
        self.run_import(
            [facility(1)], [herd(1, 2023)],
            [[1, 2015, 'NaN', 'DDRDP'], [1, 2019, '2022', 'AgSTAR'], [99, 2020, 'NaN', 'LCFS']],
        )
        rows = list(Digester.objects.order_by('operational_year').values_list('operational_year', 'shutdown_year', 'source'))
        assert rows == [(2015, None, 'DDRDP'), (2019, 2022, 'AgSTAR')]
        assert Digester.objects.operating_in(2014).count() == 0
        assert Digester.objects.operating_in(2021).count() == 2
        assert Digester.objects.operating_in(2022).count() == 1
        assert Digester.objects.get(operational_year=2019).operating_in(2022) is False

    def test_digester_with_unknown_operational_year_is_kept(self):
        # CADD carries a handful of AgSTAR rows with no recorded start year.
        self.run_import([facility(1)], [herd(1, 2023)], [[1, 'NaN', 'NaN', 'AgSTAR']])
        digester = Digester.objects.get()
        assert digester.operational_year is None
        assert digester.operating_in(2023) is True
        assert Digester.objects.operating_in(2023).count() == 1

    def test_unknown_counties_and_missing_coordinates_are_reported(self):
        # A covered county with no Region loaded, and a blank county name.
        Region.objects.filter(type=Region.Type.COUNTY, slug='madera').update(name='Madera (retired)')
        output = self.run_import([facility(1), facility(2, 'Madera'), facility(3, ''), facility(4, lat=None, lng=None)])
        assert list(Dairy.objects.values_list('cadd_id', flat=True)) == [1]
        assert 'Skipped, no coordinates: 1.' in output
        assert 'Skipped, unknown county: (blank) (1), Madera (1).' in output

    def test_a_missing_column_fails_and_writes_nothing(self):
        self.run_import([facility(1)], [herd(1, 2023, milk=100)])
        write_workbook(self.path, [facility(1), facility(2)], [herd(1, 2023, milk=500)], drop=('Facility Herd Size', 'MilkCows'))
        with pytest.raises(CommandError, match='MilkCows'):
            call_command('import_cadd', '--path', self.path, stdout=io.StringIO())
        assert Dairy.objects.count() == 1
        assert DairyHerd.objects.get().milk_cows == 100

    def test_clears_the_dairy_caches(self):
        before = dairies.generation()
        self.run_import([facility(1)], [herd(1, 2023)])
        assert dairies.generation() == before + 1

    def test_downloads_from_the_url(self):
        write_workbook(self.path, [facility(1)], [herd(1, 2023)])
        with open(self.path, 'rb') as handle:
            response = MagicMock(content=handle.read())
        response.raise_for_status.return_value = None
        with patch('camp.apps.emissions.management.commands.import_cadd.requests.get', return_value=response) as get:
            call_command('import_cadd', '--url', stdout=io.StringIO())
        assert get.call_args[0][0] == cadd.URL
        assert Dairy.objects.count() == 1


class SizeClassTests(TestCase):
    """EPA's dairy thresholds (40 CFR 122.23(b)(4),(6)): the larger of the two counts' classes wins."""

    def test_mature_dairy_cow_boundaries(self):
        assert size_class(1, 0) == SizeClass.SMALL
        assert size_class(199, 0) == SizeClass.SMALL
        assert size_class(200, 0) == SizeClass.MEDIUM
        assert size_class(699, 0) == SizeClass.MEDIUM
        assert size_class(700, 0) == SizeClass.LARGE

    def test_other_cattle_boundaries(self):
        assert size_class(0, 299) == SizeClass.SMALL
        assert size_class(0, 300) == SizeClass.MEDIUM
        assert size_class(0, 999) == SizeClass.MEDIUM
        assert size_class(0, 1000) == SizeClass.LARGE

    def test_the_larger_class_wins(self):
        assert size_class(100, 1000) == SizeClass.LARGE
        assert size_class(700, 10) == SizeClass.LARGE
        assert size_class(199, 300) == SizeClass.MEDIUM
        assert size_class(250, 50) == SizeClass.MEDIUM
        # Both just under Medium: still Small, however many head in all.
        assert size_class(199, 299) == SizeClass.SMALL

    def test_no_cattle_has_no_class(self):
        assert size_class(0, 0) == ''

    def test_a_beef_only_site(self):
        totals = herd_totals({'milk_cows': 0, 'dry_cows': None, 'beef_cattle': 450})
        assert totals == {'mature_cows': 0, 'other_cattle': 450, 'size_class': SizeClass.MEDIUM}

    def test_dry_cows_are_mature_and_blank_counts_are_left_out(self):
        totals = herd_totals({
            'milk_cows': 600, 'dry_cows': 100, 'old_heifers': 200, 'young_heifers': None,
            'old_calves': 50, 'young_calves': 25, 'beef_cattle': None,
        })
        assert totals == {'mature_cows': 700, 'other_cattle': 275, 'size_class': SizeClass.LARGE}
