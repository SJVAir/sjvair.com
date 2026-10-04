from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, Commodity, PesticideUse, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.pesticides.views import RecordsBrowser
from camp.apps.regions.models import Boundary, Region


def browser(params):
    """A RecordsBrowser with its filters resolved from `params`, without rendering."""
    view = RecordsBrowser()
    view.request = RequestFactory().get(reverse('pesticides:records'), params)
    view._resolve_filters(view.request)
    return view


class RecordsTotalsFromRollupTests(RollupTestMixin, TestCase):
    """
    The records browser's four totals read the rollup when every filter is in
    its grain. Whatever the path, the numbers must be what the raw records
    give: the rollup is a speed-up, never a different answer.
    """
    fixtures = ['pesticides-explorer']

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()  # loads the fixture
        fresno, kern = Region.objects.get(pk=9001), Region.objects.get(pk=9002)
        base = dict(year=2023, county=fresno, mtrs_id=9101, product_id=1, commodity_id=1, acres_treated=12, aerial_ground='G')
        # One report with three ingredients (two chemicals of concern and a
        # plain one): three rows, one record, acres repeated on every row.
        for chemical_id, lbs in ((1, 10), (3, 20), (2, 30)):
            PesticideUse.objects.create(
                use_no=50, chemical_id=chemical_id, lbs_chemical=lbs, lbs_product=60,
                application_date='2023-09-01', **base,
            )
        # A report with a restricted ingredient and one that is only flagged.
        for chemical_id, lbs in ((1, 5), (2, 7)):
            PesticideUse.objects.create(
                use_no=51, chemical_id=chemical_id, lbs_chemical=lbs, lbs_product=12,
                application_date='2023-10-01', **{**base, 'product_id': 2, 'commodity_id': 3, 'acres_treated': 3},
            )
        # No application date: no date range holds it, the rollup's month 0.
        PesticideUse.objects.create(
            use_no=52, chemical_id=1, lbs_chemical=99, lbs_product=99, application_date=None,
            **{**base, 'acres_treated': 9},
        )
        # No chemical, section, product or commodity, and no method reported.
        PesticideUse.objects.create(
            year=2023, use_no=53, county=kern, mtrs=None, product=None, chemical=None, commodity=None,
            lbs_chemical=None, lbs_product=None, acres_treated=None, application_date='2023-02-01', aerial_ground='',
        )
        # A place that holds the Fresno section.
        city = Region.objects.create(name='Fresnoville', slug='fresnoville', type=Region.Type.CITY, external_id='c-9')
        Boundary.objects.create(
            region=city, version='test', metadata={},
            geometry=MultiPolygon(Polygon(((-120.4, 36.1), (-119.1, 36.1), (-119.1, 36.9), (-120.4, 36.9), (-120.4, 36.1)))),
        )
        cls.city = city
        # Rebuild now that the extra rows exist.
        from camp.apps.pesticides import rollup
        rollup.rebuild_all()

    def setUp(self):
        super().setUp()
        cache.clear()

    def sqid(self, model, **kwargs):
        return model.objects.get(**kwargs).sqid

    def filter_sets(self):
        return {
            'default year': {},
            'all years': {'year': 'all'},
            'earlier year': {'year': 2022},
            'county': {'county': 'fresno'},
            'other county': {'county': 'kern'},
            'region (county)': {'region': Region.objects.get(pk=9001).sqid},
            'region (place)': {'region': self.city.sqid},
            'region and county': {'region': self.city.sqid, 'county': 'kern'},
            'section': {'section': Region.objects.get(pk=9101).sqid},
            'chemical': {'chemical': Chemical.objects.get(pk=1).sqid},
            'chemical, all years': {'chemical': Chemical.objects.get(pk=1).sqid, 'year': 'all'},
            'product': {'product': Product.objects.get(pk=1).sqid},
            'commodity': {'commodity': Commodity.objects.get(pk=3).sqid},
            'method A': {'method': 'A'},
            'method G': {'method': 'G'},
            'method none': {'method': 'none'},
            'narrow concern': {'narrow': 'concern'},
            'narrow restricted': {'narrow': 'restricted'},
            'narrow fumigant': {'narrow': 'fumigant'},
            'narrow aerial': {'narrow': 'aerial'},
            'combination': {
                'county': 'fresno', 'narrow': 'concern', 'method': 'G', 'product': Product.objects.get(pk=1).sqid,
            },
            'chemical and narrow': {'chemical': Chemical.objects.get(pk=2).sqid, 'narrow': 'restricted'},
            'whole year typed out': {'start': '2023-01-01', 'end': '2023-12-31'},
        }

    def assert_same(self, raw, rolled, label):
        assert rolled['applications'] == raw['applications'], label
        assert rolled['records'] == raw['records'], label
        assert rolled['lbs'] == raw['lbs'], label
        assert rolled['acres'] == raw['acres'], label

    def test_rollup_totals_equal_the_raw_totals_for_every_answerable_filter(self):
        for label, params in self.filter_sets().items():
            view = browser(params)
            assert view._totals_from_rollup(), label
            self.assert_same(view._raw_totals(), view._rollup_totals(), label)

    def test_the_fixture_is_not_trivial(self):
        # A guard on the test data: a multi-ingredient report makes rows
        # differ from records, which is what the rollup must get right.
        totals = browser({})._raw_totals()
        assert totals['applications'] > totals['records'] > 0
        assert totals['acres'] > 0 and totals['lbs'] > 0

    def test_rows_without_an_application_date_are_left_out(self):
        # The raw date filter never matches them; the rollup keeps them in month 0.
        view = browser({})
        assert PesticideUse.objects.filter(year=2023, application_date__isnull=True).count() == 1
        assert view._rollup_totals()['applications'] == view._raw_totals()['applications']

    def test_get_totals_takes_the_rollup_when_it_can(self):
        view = browser({'county': 'fresno'})
        raw = view._raw_totals()
        with self.assertNumQueries(1):  # one rollup aggregate, nothing against the records
            totals = view._rollup_totals()
        assert totals == raw
        assert view.get_totals() == raw

    def test_custom_date_range_takes_the_raw_path(self):
        assert not browser({'start': '2023-05-01', 'end': '2023-07-31'})._totals_from_rollup()
        assert not browser({'start': '2023-05-01'})._totals_from_rollup()
        assert not browser({'year': 'all', 'start': '2022-03-01', 'end': '2023-06-30'})._totals_from_rollup()

    def test_fumigation_technique_takes_the_raw_path(self):
        from camp.apps.pesticides.models import FumigationMethod
        FumigationMethod.objects.create(code=1107, name='Tarpaulin')
        PesticideUse.objects.filter(pk=1).update(fume_method=FumigationMethod.objects.get(code=1107))
        assert not browser({'fume_method': 1107})._totals_from_rollup()

    def test_point_and_radius_take_the_raw_path(self):
        assert not browser({'lat': 36.5, 'lng': -119.8, 'radius': 1})._totals_from_rollup()

    def test_a_section_or_region_beats_the_point_as_in_the_raw_filter(self):
        # area_filter ignores the point when a section is given, so the rollup can answer.
        view = browser({'section': Region.objects.get(pk=9101).sqid, 'lat': 36.5, 'lng': -119.8, 'radius': 1})
        assert view._totals_from_rollup()
        self.assert_same(view._raw_totals(), view._rollup_totals(), 'section + point')

    def test_an_unresolved_entity_takes_the_raw_path(self):
        view = browser({'chemical': 'nope'})
        assert not view._totals_from_rollup()
        assert view.get_totals() == {'applications': 0, 'records': 0, 'lbs': 0, 'acres': 0}

    def test_the_paginator_count_is_the_row_count_on_the_rollup_path(self):
        for params in ({}, {'county': 'fresno'}, {'narrow': 'concern'}, {'method': 'A'}, {'year': 'all'}):
            view = browser(params)
            assert view._totals_from_rollup()
            count = view.get_paginator(view.get_queryset(), 50).count
            assert count == view.get_filtered_queryset().count(), params

    def test_page_context_totals_match(self):
        response = self.client.get(reverse('pesticides:records'), {'county': 'fresno', 'narrow': 'concern'})
        view = browser({'county': 'fresno', 'narrow': 'concern'})
        assert response.context['totals'] == view._raw_totals()

    def test_each_county_has_its_own_cached_totals(self):
        valley = browser({}).get_totals()
        fresno = browser({'county': 'fresno'}).get_totals()
        kern = browser({'county': 'kern'}).get_totals()
        assert valley['applications'] > fresno['applications'] > kern['applications']
