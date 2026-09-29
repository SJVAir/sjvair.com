"""
data/ddrdp-page.pdf is page 2 of CDFA's DDRDP project-level PDF, extracted
with `qpdf --pages ... 2 -- ddrdp-page.pdf` (Task 7 Step 2). Every page of
the real PDF repeats the "Updated <date>" header line, and page 2's reads
7/13/2026 -- a few weeks after page 1's 6/27/2026 (the report tool appears
to stamp each page as it's rendered, not the data's as-of date); parse()
only ever reads page 1 of a real, full download, so this is solely an
artifact of the sample being a single extracted page. It has 28 real
projects, including two ("De Groot North Dairy Biogas", "Milky Way Dairy
Biogas") CDFA marked cancelled: those rows carry a cancellation note in
place of the GHG figure and have no city/county/dates, which is why
test_the_real_page doesn't require every row to have a county -- only that
project_name/dairy_name and grant_amount are always there (the real PDF
has 157 projects across 6 pages, 141 of them with a county; see the PR
notes for the full-file count).
"""
from decimal import Decimal
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import dairies
from camp.apps.emissions.importers import ddrdp
from camp.apps.emissions.models import DigesterGrant, SourceImport
from camp.apps.emissions.tests.test_dairies import make_dairies

SAMPLE = Path(__file__).parent / 'data' / 'ddrdp-page.pdf'


class ParseTests(TestCase):
    def test_the_real_page(self):
        rows, version = ddrdp.parse(SAMPLE)
        assert len(rows) == 28
        assert version == '2026-07-13'  # this page's own "Updated" stamp -- see the module docstring
        first = rows[0]
        assert set(first) == {
            'project_name', 'dairy_name', 'city', 'county', 'developer', 'grant_amount',
            'end_use', 'est_reduction_tco2e', 'awarded', 'operational',
        }
        assert all(r['dairy_name'] for r in rows)
        # Two of the 28 are CDFA-cancelled projects with no city/county/dates.
        assert sum(1 for r in rows if r['county']) == 26
        assert sum(1 for r in rows if r['grant_amount'] is not None) == 28
        assert all(r['grant_amount'] is None or isinstance(r['grant_amount'], Decimal) for r in rows)
        cancelled = next(r for r in rows if r['project_name'] == 'De Groot North Dairy Biogas')
        assert (cancelled['county'], cancelled['city'], cancelled['awarded'], cancelled['est_reduction_tco2e']) == ('', '', None, None)
        assert cancelled['grant_amount'] == Decimal('1442440')
        normal = rows[0]  # 'BV Dairy Biogas', a normal row
        assert (normal['project_name'], normal['city'], normal['county'], normal['developer']) == ('BV Dairy Biogas', 'Bakersfield', 'Kern', 'California Bioenergy')
        assert normal['grant_amount'] == Decimal('1749596')
        assert normal['est_reduction_tco2e'] == 20584.0
        assert normal['end_use'] == 'RNG'
        assert normal['awarded'].isoformat() == '2018-07-01'
        assert normal['operational'].isoformat() == '2020-09-18'

    def test_normalise_name(self):
        # 'Lakeside Dairy, LLC' and 'LAKESIDE DAIRY' meeting is the one hard
        # requirement (the plan's own note): plain generic words (dairy,
        # llc) are dropped unless nothing would be left. "j d farms" isn't
        # asserted here -- naive stopword-dropping gives "j d" instead, which
        # the plan's own docstring flags as an open call; this project keeps
        # the naive rule.
        assert ddrdp.normalise_name('Lakeside Dairy, LLC') == 'lakeside'
        # CDFA's grant words go too, so a project title meets its CADD dairy.
        assert ddrdp.normalise_name('Scheenstra Dairy Biogas') == ddrdp.normalise_name('Scheenstra Dairy') == 'scheenstra'
        assert ddrdp.normalise_name('Fern Oaks Dairy Digester Pipeline Project') == 'fern oaks'
        assert ddrdp.normalise_name('LAKESIDE DAIRY') == 'lakeside'
        assert ddrdp.normalise_name('J & D Farms Inc.') == 'j d'
        assert ddrdp.normalise_name('Big Dairy #2') == 'big 2'


class MatchAndApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()

    def row(self, **overrides):
        values = dict(
            project_name='Big Dairy Digester', dairy_name='Big Dairy', city='Riverdale', county='Fresno',
            developer='Dev Co', grant_amount=Decimal('1500000'), end_use='Pipeline injection',
            est_reduction_tco2e=12000.0, awarded=None, operational=None,
        )
        values.update(overrides)
        return values

    def test_two_match_paths_and_unmatched(self):
        from camp.apps.emissions.importers import ddrdp_crosswalk
        ddrdp_crosswalk.CROSSWALK['mystery'] = self.small.cadd_id
        try:
            rows = ddrdp.match([
                self.row(),
                self.row(project_name='Mystery Digester', dairy_name='Mystery', city='Nowhere'),
                self.row(project_name='Lost', dairy_name='Lost Dairy', city='Nowhere'),
            ])
        finally:
            del ddrdp_crosswalk.CROSSWALK['mystery']
        assert [(r['dairy'], r['match_method']) for r in rows] == [(self.big, 'auto'), (self.small, 'manual'), (None, '')]

    def test_apply_replaces_and_stamps(self):
        ddrdp.apply(ddrdp.match([self.row()]), '2026-06-27')
        ddrdp.apply(ddrdp.match([
            self.row(),
            self.row(project_name='Second', dairy_name='Small Dairy', city='Bakersfield', county='Kern',
                      grant_amount=Decimal('900000'), est_reduction_tco2e=5000.0),
        ]), '2026-06-27')
        assert DigesterGrant.objects.count() == 2 and SourceImport.latest('ddrdp').version == '2026-06-27'
        totals = dairies.grant_totals(self.big.county)
        assert totals == {'grants': 1, 'amount': Decimal('1500000'), 'reduction': 12000.0}
        assert dairies.grant_totals(self.closed.county) == totals  # same county

    def test_county_totals_none_with_no_rows(self):
        assert dairies.grant_totals(self.big.county) is None
