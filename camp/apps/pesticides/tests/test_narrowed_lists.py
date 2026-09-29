from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import Chemical, Commodity, PesticideUseRollup, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


NARROWS = ('aerial', 'fumigant', 'restricted', 'concern')
LIST_SPECS = (
    ('pesticides:chemical-list', 'chemical', 'lbs_chemical'),
    ('pesticides:product-list', 'product', 'lbs_product'),
    ('pesticides:commodity-list', 'commodity', 'lbs_chemical'),
)


class NarrowedListTests(RollupTestMixin, TestCase):
    """The narrowed list pages read one cached group-by; it must agree with the rollup."""

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def expected(self, field, lbs_field, narrow, year=None):
        rows = stats.narrow_rows(PesticideUseRollup.objects.filter(**{f'{field}__isnull': False}), narrow)
        if year:
            rows = rows.filter(year=year)
        return {pk: lbs for pk, lbs in rows.values_list(field).annotate(s=Sum(lbs_field))}

    def listed(self, url_name, narrow, **params):
        response = self.client.get(reverse(url_name), {'narrow': narrow, **params})
        assert response.status_code == 200
        return {obj.pk: obj.lbs_applied for obj in response.context['object_list']}

    def test_lists_match_the_rollup_for_every_narrowing(self):
        for url_name, field, lbs_field in LIST_SPECS:
            for narrow in NARROWS:
                for params, year in (({'year': 'all'}, None), ({'year': '2023'}, 2023), ({'year': '2022'}, 2022)):
                    expected = self.expected(field, lbs_field, narrow, year)
                    listed = self.listed(url_name, narrow, **params)
                    # Placeholder chemicals and the like are filtered by the page, not by us.
                    assert set(listed) <= set(expected), (url_name, narrow, params)
                    for pk, lbs in listed.items():
                        assert lbs == expected[pk], (url_name, narrow, params, pk)
                    if field != 'chemical':
                        assert set(listed) == set(expected), (url_name, narrow, params)

    def test_lists_narrowed_to_air_hold_only_air_entities(self):
        listed = self.listed('pesticides:chemical-list', 'aerial', year='2023')
        assert listed
        assert sum(listed.values()) == 70.0

    def test_county_scope_narrows_the_group_by(self):
        listed = self.listed('pesticides:chemical-list', 'aerial', year='2023', county='fresno')
        assert listed == {}
        listed = self.listed('pesticides:chemical-list', 'aerial', year='2023', county='kern')
        assert sum(listed.values()) == 70.0

    def test_an_entity_filter_still_reports_the_pairs_pounds(self):
        # Under a related filter the column is the pair's pounds, so the
        # group-by (the entity's own pounds) must not stand in for it.
        chemical = Chemical.objects.get(pk=1)
        response = self.client.get(reverse('pesticides:commodity-list'), {
            'narrow': 'fumigant', 'year': '2023', 'chemical': chemical.sqid,
        })
        expected = dict(PesticideUseRollup.objects.filter(year=2023, chemical=chemical, product__is_fumigant=True)
            .values_list('commodity').annotate(s=Sum('lbs_chemical')))
        assert {c.pk: c.lbs_applied for c in response.context['object_list']} == expected

    def test_the_group_by_is_cached(self):
        expected = self.expected('chemical', 'lbs_chemical', 'aerial', 2023)
        assert stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', 2023) == expected
        with self.assertNumQueries(0):
            assert stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', 2023) == expected
            assert stats.narrowed_keys('chemical', 'aerial', 2023) == set(expected)

    def test_the_scope_is_part_of_the_cache_key(self):
        assert stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', 2023) != stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', 2022)
        assert stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', all_years=True)
        assert stats.narrowed_lbs('chemical', 'lbs_chemical', 'aerial', 2023, county='fresno') == {}

    def rollup_group_bys(self, url, **params):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(url, params)
        return len([q for q in queries if 'GROUP BY' in q['sql'] and 'pesticideuserollup' in q['sql']])

    def test_a_warm_list_request_reads_no_rollup_group_by(self):
        url = reverse('pesticides:product-list')
        assert self.rollup_group_bys(url, narrow='aerial', year='all') >= 1
        assert self.rollup_group_bys(url, narrow='aerial', year='all') == 0


class NarrowedEntitySearchTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('api:v2:pesticides:entity-search')

    def names(self, **params):
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        return [r['name'] for r in response.json()['results']]

    def test_search_keeps_only_what_the_narrowing_keeps(self):
        for kind, model, query in (('chemical', Chemical, 'gl'), ('product', Product, 'ro'), ('commodity', Commodity, 'gr')):
            kept = set(stats.narrowed_keys(kind, 'fumigant', all_years=True))
            expected = {name for name in self.names(type=kind, q=query)
                if model.objects.get(pk=self.pk_of(kind, name)).pk in kept}
            assert set(self.names(type=kind, q=query, narrow='fumigant')) == expected

    def pk_of(self, kind, display_name):
        model = {'chemical': Chemical, 'product': Product, 'commodity': Commodity}[kind]
        return next(obj.pk for obj in model.objects.all() if obj.display_name == display_name)

    def test_search_scopes_the_narrowing_by_year_and_county(self):
        assert self.names(type='chemical', q='sulf', narrow='aerial', year='2023') == []
        year_keys = stats.narrowed_keys('product', 'aerial', 2023)
        products = self.names(type='product', q='pro', narrow='aerial', year='2023')
        assert len(products) <= len(year_keys)
        assert self.names(type='commodity', q='gra', narrow='aerial', county='fresno', year='2023') == []

    def test_search_reads_the_cached_key_set(self):
        self.names(type='product', q='pro', narrow='fumigant', year='2023')
        with CaptureQueriesContext(connection) as queries:
            self.names(type='product', q='rou', narrow='fumigant', year='2023')
        assert not [q for q in queries if 'pesticideuserollup' in q['sql']]
