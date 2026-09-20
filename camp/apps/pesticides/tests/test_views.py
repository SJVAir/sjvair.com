from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideUseRollup, PesticideUseTotal, Product, ProductChemical,
)
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class ChemicalListTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:chemical-list')

    def names(self, response):
        return [c.name for c in response.context['object_list']]

    def test_unused_in_year_is_hidden(self):
        Chemical.objects.create(chem_code=30001, name='NEVER USED')
        assert 'NEVER USED' not in self.names(self.client.get(self.url, {'sort': 'name'}))
        assert self.client.get(self.url, {'q': 'never'}).context['result_count'] == 0

    def test_county_filter_limits_rows_and_pounds(self):
        # Kern 2023: uses 3 (glyphosate, 30 lbs) and 5 (chlorpyrifos, 40 lbs); no sulfur.
        response = self.client.get(self.url, {'county': 'kern'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('CHLORPYRIFOS', 40.0), ('GLYPHOSATE', 30.0),
        ]
        assert 'used in Kern County' in response.context['summary_sentence']
        assert self.client.get(self.url, {'county': 'nope'}).context['result_count'] == 3

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/chemical-list.html')
        assert response.context['result_count'] == 3
        assert response.context['latest_year'] == 2023

    def test_year_param_switches_the_pounds_column(self):
        response = self.client.get(self.url, {'year': '2022'})
        assert response.context['year'] == 2022
        assert response.context['latest_year'] == 2023
        assert response.context['year_options'] == [2022, 2023]
        assert response.context['year_qs'] == '?year=2022'
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('SULFUR', 400.0), ('GLYPHOSATE', 80.0), ('CHLORPYRIFOS', 60.0),
        ]
        html = response.content.decode()
        assert Chemical.objects.get(pk=1).get_absolute_url() + '?year=2022' in html
        assert 'year=2022' in html and 'aria-current="page"' in html

    def test_unknown_year_falls_back_to_latest(self):
        response = self.client.get(self.url, {'year': '1999'})
        assert response.context['year'] == 2023
        assert response.context['year_qs'] == ''

    def test_all_years_sums_every_loaded_year(self):
        response = self.client.get(self.url, {'year': 'all'})
        assert response.context['all_years'] is True
        assert response.context['year'] is None
        assert response.context['year_label'] == '2022\u20132023'
        assert response.context['year_qs'] == '?year=all'
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('SULFUR', 900.0), ('GLYPHOSATE', 260.0), ('CHLORPYRIFOS', 120.0),
        ]
        assert response.context['summary_sentence'] == '3 chemicals used 2022\u20132023'
        html = response.content.decode()
        assert 'Lbs applied' in html  # the year lives in the summary line, not the column header
        # The hero gains an All pill and a matching option in the mobile select.
        assert '>All<' in html and '>All years</option>' in html
        assert Chemical.objects.get(pk=1).get_absolute_url() + '?year=all' in html

    def test_all_years_with_a_county(self):
        response = self.client.get(self.url, {'year': 'all', 'county': 'kern'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('CHLORPYRIFOS', 100.0), ('GLYPHOSATE', 30.0),
        ]
        assert response.context['summary_sentence'] == '2 chemicals used in Kern County 2022\u20132023'

    def test_year_select_shows_the_resolved_year(self):
        html = self.client.get(self.url).content.decode()
        assert '<option value="2023" selected>2023</option>' in html
        html = self.client.get(self.url, {'year': 'all'}).content.decode()
        assert '<option value="all" selected>All years</option>' in html

    def test_default_sort_is_lbs_desc(self):
        response = self.client.get(self.url)
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        lbs = [c.lbs_applied for c in response.context['object_list']]
        assert lbs == [500.0, 180.0, 60.0]

    def test_sort_by_name(self):
        response = self.client.get(self.url, {'sort': 'name'})
        assert self.names(response) == ['CHLORPYRIFOS', 'GLYPHOSATE', 'SULFUR']
        response = self.client.get(self.url, {'sort': '-name'})
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']

    def test_unknown_sort_falls_back(self):
        response = self.client.get(self.url, {'sort': 'evil'})
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']

    def test_search_orders_by_rank(self):
        response = self.client.get(self.url, {'q': 'chlor'})
        assert self.names(response) == ['CHLORPYRIFOS']
        assert 'matching' in response.context['summary_sentence']

    def test_preferred_name_is_shown_searched_and_sorted(self):
        # CDPR calls it "1080"; CompTox's preferred name is what the reader sees.
        Chemical.objects.filter(pk=3).update(preferred_name='Sodium fluoroacetate', name='1080')
        html = self.client.get(self.url).content.decode()
        assert 'Sodium fluoroacetate' in html
        assert '>1080<' not in html
        # Both names find it.
        assert self.names(self.client.get(self.url, {'q': 'fluoroacetate'})) == ['1080']
        assert self.names(self.client.get(self.url, {'q': '1080'})) == ['1080']
        # Sorting by name follows the shown name: "Sodium fluoroacetate" sorts last.
        assert self.names(self.client.get(self.url, {'sort': 'name'})) == ['CHLORPYRIFOS', 'GLYPHOSATE', '1080']

    def test_category_filter_is_or(self):
        response = self.client.get(self.url, {'category': ['carcinogen', 'toxic_air_contaminant']})
        assert set(self.names(response)) == {'GLYPHOSATE', 'CHLORPYRIFOS'}

    def test_iarc_filter(self):
        response = self.client.get(self.url, {'iarc_group': '2A'})
        assert self.names(response) == ['GLYPHOSATE']

    def test_invalid_iarc_ignored(self):
        response = self.client.get(self.url, {'iarc_group': '9Z'})
        assert response.status_code == 200
        assert response.context['result_count'] == 3

    def test_product_count_annotation(self):
        response = self.client.get(self.url, {'sort': 'name'})
        assert [c.product_count for c in response.context['object_list']] == [1, 1, 1]

    def test_product_count_not_collapsed_by_related_filter(self):
        # GLYPHOSATE (pk=1) already sits in ROUNDUP PRO (pk=1); give it a
        # second product so the true product_count is 2, then filter the
        # list by ROUNDUP PRO and confirm the count isn't restricted to the
        # filtered join.
        second_product = Product.objects.create(
            prodno=999, reg_number='999-999', name='WEED-B-GON',
        )
        ProductChemical.objects.create(product=second_product, chemical_id=1, pct_active=10.0)

        roundup = Product.objects.get(pk=1)
        response = self.client.get(self.url, {'product': roundup.sqid})
        by_name = {c.name: c.product_count for c in response.context['object_list']}
        assert by_name['GLYPHOSATE'] == 2

        # Unfiltered counts are unaffected.
        response = self.client.get(self.url, {'sort': 'name'})
        by_name = {c.name: c.product_count for c in response.context['object_list']}
        assert by_name == {'CHLORPYRIFOS': 1, 'GLYPHOSATE': 2, 'SULFUR': 1}

    def test_related_filter_by_product(self):
        product = Product.objects.get(pk=2)
        response = self.client.get(self.url, {'product': product.sqid})
        assert self.names(response) == ['CHLORPYRIFOS']
        assert response.context['related']['product'] == product

    def test_related_filter_by_commodity(self):
        commodity = Commodity.objects.get(pk=1)
        response = self.client.get(self.url, {'commodity': commodity.sqid})
        assert set(self.names(response)) == {'GLYPHOSATE', 'CHLORPYRIFOS'}

    def test_unknown_related_sqid_is_empty(self):
        response = self.client.get(self.url, {'product': 'nope'})
        assert response.context['result_count'] == 0

    def test_entity_pickers_for_the_other_two_kinds(self):
        html = self.client.get(self.url).content.decode()
        assert 'data-kind="product"' in html
        assert 'data-kind="commodity"' in html
        assert 'data-kind="chemical"' not in html
        # The lists submit on select: their form is the boosted one.
        assert 'data-autosubmit="1"' in html
        assert 'data-search-url="/api/2.0/pesticides/search/"' in html

    def test_selected_entity_renders_as_a_tag(self):
        product = Product.objects.get(pk=2)
        html = self.client.get(self.url, {'product': product.sqid}).content.decode()
        assert f'<input type="hidden" name="product" value="{product.sqid}">' in html
        assert escape(product.name) in html
        assert 'entity-picker-clear' in html

    def used_chemical(self, **fields):
        # Lists only show entities with use in the year, and read their pounds
        # off the totals table, so give each a rollup row and its total.
        chemical = Chemical.objects.create(**fields)
        PesticideUseRollup.objects.create(year=2023, month=1, county_id=9001, chemical=chemical, lbs_chemical=1, applications=1)
        PesticideUseTotal.objects.create(year=2023, county_id=9001, chemical=chemical, lbs_chemical=1, applications=1)
        return chemical

    def test_pagination_links_keep_filters(self):
        for i in range(60):
            self.used_chemical(chem_code=10000 + i, name=f'TEST {i}', categories=['oil'])
        response = self.client.get(self.url, {'category': 'oil', 'sort': 'name'})
        assert response.context['is_paginated'] is True
        assert 'category=oil' in response.content.decode()
        assert 'page=2' in response.content.decode()

    def test_rows_link_to_detail(self):
        response = self.client.get(self.url)
        assert Chemical.objects.get(pk=1).get_absolute_url() in response.content.decode()

    def test_empty_database(self):
        Chemical.objects.all().delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['result_count'] == 0

    def test_ties_break_on_pk_for_stable_pagination(self):
        # Two chemicals with identical names (and no uses, so lbs_applied
        # ties too) must still come back in a deterministic order so
        # pagination doesn't skip/duplicate rows across pages.
        a = self.used_chemical(chem_code=20001, name='DUPLICATE')
        b = self.used_chemical(chem_code=20002, name='DUPLICATE')

        response = self.client.get(self.url, {'sort': 'name'})
        ids = [c.pk for c in response.context['object_list'] if c.name == 'DUPLICATE']
        assert ids == sorted([a.pk, b.pk])

        response = self.client.get(self.url, {'sort': '-lbs'})
        ids = [c.pk for c in response.context['object_list'] if c.name == 'DUPLICATE']
        assert ids == sorted([a.pk, b.pk])


class ProductListTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:product-list')

    def names(self, response):
        return [p.name for p in response.context['object_list']]

    def test_renders_sorted_by_name(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert self.names(response) == ['LORSBAN 4E', 'ROUNDUP PRO', 'SULFUR DUST']

    def test_lbs_uses_lbs_product(self):
        response = self.client.get(self.url, {'sort': '-lbs'})
        rows = response.context['object_list']
        assert [(p.name, p.lbs_applied) for p in rows] == [('SULFUR DUST', 550.0), ('ROUNDUP PRO', 450.0), ('LORSBAN 4E', 135.0)]

    def test_fumigant_filter(self):
        assert self.names(self.client.get(self.url, {'fumigant': 'true'})) == ['LORSBAN 4E']
        assert self.names(self.client.get(self.url, {'fumigant': 'false'})) == ['ROUNDUP PRO', 'SULFUR DUST']

    def test_restricted_filter(self):
        assert self.names(self.client.get(self.url, {'california_restricted': 'true'})) == ['LORSBAN 4E']

    def test_search_by_reg_number(self):
        assert self.names(self.client.get(self.url, {'q': '524-475'})) == ['ROUNDUP PRO']

    def test_related_chemical(self):
        chem = Chemical.objects.get(pk=1)
        assert self.names(self.client.get(self.url, {'chemical': chem.sqid})) == ['ROUNDUP PRO']

    def test_related_commodity(self):
        commodity = Commodity.objects.get(pk=2)   # GRAPE: roundup + sulfur dust
        assert self.names(self.client.get(self.url, {'commodity': commodity.sqid})) == ['ROUNDUP PRO', 'SULFUR DUST']

    def test_entity_pickers_for_the_other_two_kinds(self):
        html = self.client.get(self.url).content.decode()
        assert 'data-kind="chemical"' in html
        assert 'data-kind="commodity"' in html
        assert 'data-kind="product"' not in html

    def test_chemical_count(self):
        response = self.client.get(self.url)
        assert [p.chemical_count for p in response.context['object_list']] == [1, 1, 1]

    def test_chemical_count_not_collapsed_by_related_filter(self):
        # ROUNDUP PRO (pk=1) already contains GLYPHOSATE (pk=1); give it a
        # second chemical so the true chemical_count is 2, then filter the
        # list by GLYPHOSATE and confirm the count isn't restricted to the
        # filtered join.
        second_chemical = Chemical.objects.create(chem_code=9999, name='SECOND CHEM')
        ProductChemical.objects.create(product_id=1, chemical=second_chemical, pct_active=5.0)

        glyphosate = Chemical.objects.get(pk=1)
        response = self.client.get(self.url, {'chemical': glyphosate.sqid})
        by_name = {p.name: p.chemical_count for p in response.context['object_list']}
        assert by_name['ROUNDUP PRO'] == 2


class CommodityListTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:commodity-list')

    def names(self, response):
        return [c.name for c in response.context['object_list']]

    def test_default_sort_lbs(self):
        response = self.client.get(self.url)
        assert self.names(response) == ['GRAPE', 'ALMOND', 'COTTON']
        assert [c.lbs_applied for c in response.context['object_list']] == [550.0, 150.0, 40.0]

    def test_chemical_count_latest_year(self):
        response = self.client.get(self.url)
        assert [(c.name, c.chemical_count) for c in response.context['object_list']] == [('GRAPE', 2), ('ALMOND', 2), ('COTTON', 1)]

    def test_search_site_code(self):
        assert self.names(self.client.get(self.url, {'q': '2500'})) == ['COTTON']

    def test_related_chemical(self):
        chem = Chemical.objects.get(pk=2)
        assert set(self.names(self.client.get(self.url, {'chemical': chem.sqid}))) == {'ALMOND', 'COTTON'}

    def test_related_product(self):
        product = Product.objects.get(pk=3)
        assert self.names(self.client.get(self.url, {'product': product.sqid})) == ['GRAPE']

    def test_entity_pickers_for_the_other_two_kinds(self):
        html = self.client.get(self.url).content.decode()
        assert 'data-kind="product"' in html
        assert 'data-kind="chemical"' in html
        assert 'data-kind="commodity"' not in html

    def test_unused_commodity_is_hidden(self):
        # Lists only show entities with reported use in the selected year.
        Commodity.objects.create(site_code='9999', name='NOTHING')
        assert 'NOTHING' not in self.names(self.client.get(self.url, {'sort': 'chemicals'}))
        assert self.client.get(self.url).context['result_count'] == 3


class ChemicalDetailTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.chemical = Chemical.objects.get(pk=1)

    def test_renders_with_slug(self):
        response = self.client.get(self.chemical.get_absolute_url())
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/chemical-detail.html')
        assert response.context['object'] == self.chemical

    def test_wrong_slug_still_resolves(self):
        url = reverse('pesticides:chemical-detail', kwargs={'sqid': self.chemical.sqid, 'slug': 'whatever'})
        assert self.client.get(url).status_code == 200

    def test_preferred_name_heads_the_page(self):
        Chemical.objects.filter(pk=1).update(preferred_name='Glyphosate')
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert '<h1 class="mb-1">Glyphosate</h1>' in html
        assert '<title>Glyphosate |' in html
        # Same name, different casing: not worth a note.
        assert 'Listed by CDPR' not in html

    def test_cdpr_name_noted_when_it_differs(self):
        Chemical.objects.filter(pk=1).update(name='1080', preferred_name='Sodium fluoroacetate')
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert '<h1 class="mb-1">Sodium fluoroacetate</h1>' in html
        assert 'Listed by CDPR as “1080”' in html

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('pesticides:chemical-redirect', kwargs={'sqid': self.chemical.sqid}))
        assert response.status_code == 301
        assert response['Location'] == self.chemical.get_absolute_url()

    def test_bad_sqid_404(self):
        assert self.client.get('/tools/pesticides/chemicals/nope/x/').status_code == 404
        assert self.client.get('/tools/pesticides/chemicals/nope/').status_code == 404

    def test_totals_and_tables(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['totals'] == {'lbs': 180.0, 'applications': 3, 'counties': 2}
        assert [r['year'] for r in ctx['by_year']] == [2023, 2022]
        assert [r['county_name'] for r in ctx['by_county']] == ['Fresno County', 'Kern County']
        assert ctx['years'] == (2022, 2023)

    def test_related(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['related_a']['kind'] == 'products'
        assert [(r.obj.name, r.pct_active) for r in ctx['related_a']['rows']] == [('ROUNDUP PRO', 41.0)]
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['ALMOND', 'GRAPE']
        assert ctx['related_b']['show_all_url'] == reverse('pesticides:commodity-list') + f'?chemical={self.chemical.sqid}'
        assert ctx['related_a']['show_pct'] is True
        assert ctx['related_b']['show_pct'] is False
        assert ctx['related_a']['complete'] is False

    def test_notices_split(self):
        ctx = self.client.get(Chemical.objects.get(pk=2).get_absolute_url()).context
        assert [n.pk for n in ctx['upcoming']] == [2, 3]
        assert ctx['upcoming_count'] == 2
        html = self.client.get(Chemical.objects.get(pk=2).get_absolute_url()).content.decode()
        assert '2 scheduled' in html
        assert 'Upcoming notices' not in html   # not part of the year-binned stat row
        assert ctx['upcoming_by_county'][0]['county_name'] == 'Fresno County'

    def test_year_param_on_detail(self):
        ctx = self.client.get(self.chemical.get_absolute_url(), {'year': '2022'}).context
        assert ctx['year'] == 2022
        assert ctx['totals'] == {'lbs': 80.0, 'applications': 1, 'counties': 1}
        assert [r['county_name'] for r in ctx['by_county']] == ['Fresno County']
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['ALMOND']
        assert ctx['summary_sentence'] == 'Applied in 1 of 8 SJV counties in 2022, mostly on Almond.'
        assert ctx['related_b']['show_all_url'].endswith(f'?chemical={self.chemical.sqid}&year=2022')
        html = self.client.get(self.chemical.get_absolute_url(), {'year': '2022'}).content.decode()
        assert 'is-selected' in html and 'year=2023' in html

    def test_summary_sentence(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['summary_sentence'] == 'Applied in 2 of 8 SJV counties in 2023, mostly on Almond and Grape.'

    def test_all_years_on_detail(self):
        url = self.chemical.get_absolute_url()
        ctx = self.client.get(url, {'year': 'all'}).context
        assert ctx['all_years'] is True and ctx['year'] is None
        # Uses 1, 2, 3 in 2023 (180 lbs) plus use 7 in 2022 (80 lbs).
        assert ctx['totals'] == {'lbs': 260.0, 'applications': 4, 'counties': 2}
        assert [r['year'] for r in ctx['by_year']] == [2023, 2022]
        assert [(r['county_name'], r['lbs']) for r in ctx['by_county']] == [
            ('Fresno County', 230.0), ('Kern County', 30.0),
        ]
        assert ctx['by_month'][2]['lbs'] == 180.0   # March in both years
        assert [(r.obj.name, r.lbs) for r in ctx['related_b']['rows']] == [('ALMOND', 210.0), ('GRAPE', 50.0)]
        assert ctx['summary_sentence'] == 'Applied in 2 of 8 SJV counties in 2022\u20132023, mostly on Almond and Grape.'
        assert ctx['related_b']['show_all_url'].endswith(f'?chemical={self.chemical.sqid}&year=all')
        assert ctx['records_url'].endswith(f'?chemical={self.chemical.sqid}&year=all')
        html = self.client.get(url, {'year': 'all'}).content.decode()
        assert 'Lbs applied in 2022\u20132023' in html

    def test_badges_and_links_render(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'Prop 65' in html
        assert 'IARC 2A' in html
        assert 'comptox.epa.gov' in html
        assert '/api/2.0/pesticides/use/' not in html
        assert '/api/2.0/docs/#tag/pesticides' in html
        assert 'sjvair.github.io/sjvair-python' in html
        assert 'chemical=1855' in html
        assert Product.objects.get(pk=1).get_absolute_url() in html

    def test_query_ceiling(self):
        # Honest count with the current implementation is 23 (verified
        # query-by-query: every related-object fetch is batched via
        # in_bulk/prefetch/select_related, no N+1s -- 18 base queries
        # (including the by_month rollup aggregate for the future month
        # chart) plus the county map's geometry build, the by-county
        # region-name lookup, the by-county-table's in_bulk() for
        # county_sqid, and the available-years lookup for the year picker;
        # all cached after the first request).
        with self.assertNumQueries(22):
            self.client.get(self.chemical.get_absolute_url())

    def test_by_month_in_context(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert len(ctx['by_month']) == 12
        assert ctx['by_month'][2]['lbs'] == 100.0

    def test_county_map_rendered(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'admin-leaflet-map' in html
        assert 'Fresno County: 150 lbs' in html

    def test_no_map_without_uses(self):
        chem = Chemical.objects.create(chem_code=4243, name='NOTHING2')
        assert self.client.get(chem.get_absolute_url()).context['county_map'] is None

    def test_no_uses_renders_empty_state(self):
        chem = Chemical.objects.create(chem_code=4242, name='NOTHING')
        response = self.client.get(chem.get_absolute_url())
        assert response.status_code == 200
        assert response.context['totals']['applications'] == 0
        assert 'No confirmed applications' in response.content.decode()


class ProductDetailTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.product = Product.objects.get(pk=2)

    def test_renders_with_ingredients(self):
        ctx = self.client.get(self.product.get_absolute_url()).context
        assert ctx['related_a']['kind'] == 'chemicals'
        assert [(r.obj.name, r.pct_active) for r in ctx['related_a']['rows']] == [('CHLORPYRIFOS', 44.9)]
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['COTTON', 'ALMOND']
        # Ingredients are a complete list with no pounds of their own.
        card = ctx['related_a']
        assert (card['show_pct'], card['show_lbs'], card['complete']) == (True, False, True)
        html = self.client.get(self.product.get_absolute_url()).content.decode()
        assert html.count('Show all') == 1

    def test_totals_use_lbs_product(self):
        ctx = self.client.get(self.product.get_absolute_url()).context
        assert ctx['totals']['lbs'] == 135.0

    def test_inherited_badges(self):
        html = self.client.get(self.product.get_absolute_url()).content.decode()
        assert 'CARB TAC' in html
        assert 'Fumigant' in html
        assert 'CA restricted' in html

    def test_badge_tooltips_come_from_the_notes_datafile(self):
        from camp.apps.pesticides import notes
        # Product 2's only chemical is a TAC, so that's the "contains" badge
        # this fixture can exercise.
        html = self.client.get(self.product.get_absolute_url()).content.decode()
        summary = escape(notes.note('carb_tac')['summary'])
        assert f'data-tooltip="{summary}"' in html

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('pesticides:product-redirect', kwargs={'sqid': self.product.sqid}))
        assert response.status_code == 301


class CommodityDetailTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.commodity = Commodity.objects.get(pk=2)

    def test_renders(self):
        ctx = self.client.get(self.commodity.get_absolute_url()).context
        assert ctx['totals'] == {'lbs': 550.0, 'applications': 2, 'counties': 1}
        assert [r.obj.name for r in ctx['related_a']['rows']] == ['SULFUR', 'GLYPHOSATE']
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['SULFUR DUST', 'ROUNDUP PRO']
        assert ctx['has_notices'] is False
        assert ctx['related_a']['show_pct'] is False
        assert ctx['related_b']['show_pct'] is False

    def test_summary_sentence_uses_chemicals(self):
        ctx = self.client.get(self.commodity.get_absolute_url()).context
        assert ctx['summary_sentence'] == 'Applied in 1 of 8 SJV counties in 2023, mostly Sulfur and Glyphosate.'

    def test_no_notice_section(self):
        html = self.client.get(self.commodity.get_absolute_url()).content.decode()
        assert 'SprayDays notices of intent' not in html
        assert 'See all notices for' not in html


class HomeTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:home')

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/home.html')
        assert response.context['latest_year'] == 2023
        assert response.context['total_lbs'] == 740.0

    def test_year_param_on_home(self):
        response = self.client.get(self.url, {'year': '2022'})
        assert response.context['year'] == 2022
        assert response.context['total_lbs'] == 540.0
        html = response.content.decode()
        assert 'Fresno County: 480 lbs' in html
        assert Chemical.objects.get(pk=3).get_absolute_url() + '?year=2022' in html
        # The caveat still names the latest loaded year.
        assert 'the newest full year here is 2023' in html
        # Live notice count sits outside the year-binned stat row.
        assert 'Notices next 7 days' not in html
        assert 'notice-callout' in html and 'currently scheduled' in html

    def test_all_years_on_home(self):
        response = self.client.get(self.url, {'year': 'all'})
        assert response.context['all_years'] is True
        assert response.context['total_lbs'] == 1280.0
        assert response.context['applications'] == 9
        html = response.content.decode()
        assert 'Pounds applied by county, 2022\u20132023' in html
        assert 'Fresno County: 1,150 lbs' in html
        assert Chemical.objects.get(pk=3).get_absolute_url() + '?year=all' in html
        # The caveat still names the latest loaded year.
        assert 'the newest full year here is 2023' in html

    def test_leaderboards_link_to_details(self):
        html = self.client.get(self.url).content.decode()
        assert Chemical.objects.get(pk=3).get_absolute_url() in html
        assert Commodity.objects.get(pk=2).get_absolute_url() in html

    def test_explorer_region_is_boosted(self):
        html = self.client.get(self.url).content.decode()
        assert 'id="explorer"' in html
        assert 'hx-boost="true"' in html
        # Only the body swaps; the hero's tabs and year picker refresh out of band.
        assert 'hx-target="#explorer-body"' in html
        assert 'hx-select-oob="#explorer-tabs,#year-picker"' in html
        assert 'id="explorer-body"' in html and 'id="explorer-tabs"' in html and 'id="year-picker"' in html
        assert 'hx-select="#explorer-body"' in html

    def test_htmx_request_gets_full_page(self):
        # Boosted requests are ordinary GETs: the server renders the whole
        # page (title included) and htmx selects the explorer region from it.
        response = self.client.get(self.url, HTTP_HX_REQUEST='true')
        assert response.status_code == 200
        html = response.content.decode()
        assert '<title>' in html
        assert 'id="explorer"' in html

    def test_county_map(self):
        html = self.client.get(self.url).content.decode()
        assert 'Fresno County: 670 lbs' in html
        assert 'Kern County: 70 lbs' in html

    def test_about_teaser(self):
        html = self.client.get(self.url).content.decode()
        assert 'id="about"' in html
        assert reverse('pesticides:about') + '#spraydays' in html

    def test_empty_database(self):
        from camp.apps.pesticides.models import PesticideNotice, PesticideUse, PesticideUseRollup
        PesticideNotice.objects.all().delete()
        PesticideUse.objects.all().delete()
        PesticideUseRollup.objects.all().delete()
        cache.clear()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'No use data loaded' in response.content.decode()

    def test_links_to_api_docs_not_raw_endpoints(self):
        html = self.client.get(self.url).content.decode()
        assert '/api/2.0/docs/#tag/pesticides' in html
        assert 'sjvair.github.io/sjvair-python' in html
        assert '/api/2.0/pesticides/' not in html

    def test_navbar_has_data_tools(self):
        html = self.client.get(self.url).content.decode()
        assert 'Data Tools' in html
        assert 'Pesticides Explorer' in html


class MapPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:map')

    def test_renders_with_defaults(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/map.html')
        cfg = response.context['map_config']
        assert cfg['year'] == 2023
        assert cfg['center'] == '36.75,-119.80' and cfg['zoom'] == 8
        assert cfg['sections_url'] == '/api/2.0/pesticides/sections/'
        assert cfg['counties_url'] == '/api/2.0/pesticides/counties/'
        assert cfg['townships_url'] == '/api/2.0/pesticides/townships/'
        assert cfg['notices_url'] == '/api/2.0/pesticides/notices/active/'
        html = response.content.decode()
        assert 'class="section-map"' in html and 'data-year="2023"' in html
        assert 'data-counties-url="/api/2.0/pesticides/counties/"' in html
        assert 'data-townships-url="/api/2.0/pesticides/townships/"' in html
        # Popup links are built client-side from these URL patterns.
        assert 'data-product-page-url="/tools/pesticides/products/{id}/"' in html
        assert 'data-notice-page-url="/tools/pesticides/notices/{id}/"' in html
        assert 'section-map.js' in html
        assert '<noscript>' in html and 'admin-leaflet-map' in html   # static fallback

    def test_entity_filters_resolve_to_api_identifiers(self):
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(self.url, {'chemical': chem.sqid, 'year': 2022, 'county': 'fresno'})
        cfg = response.context['map_config']
        assert cfg['chemical'] == '1855' and cfg['county'] == 'fresno' and cfg['year'] == 2022
        assert [f['label'] for f in response.context['filters']] == ['Glyphosate', 'Fresno County']
        assert 'year=2022' in response.context['filters'][0]['clear_url']

    def test_unresolved_filter_says_so_instead_of_showing_everything(self):
        response = self.client.get(self.url, {'chemical': 'nope'})
        assert response.status_code == 200
        assert response.context['no_matches'] is True
        assert response.context['map_config']['chemical'] == ''
        assert response.context['county_map'] is None
        assert 'No matches for that filter' in response.content.decode()

    def test_unknown_filter_ignored(self):
        response = self.client.get(self.url, {'product': 'nope'})
        assert response.status_code == 200
        assert response.context['map_config']['product'] == ''

    def test_notices_are_on_by_default(self):
        response = self.client.get(self.url)
        assert response.context['map_config']['show_notices'] == '1'
        html = response.content.decode()
        assert 'data-show-notices="1"' in html
        assert 'name="notices" checked' in html

    def test_nav_has_map_tab(self):
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert reverse('pesticides:map') in html


class AboutTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_renders_with_anchors_and_lag_caveat(self):
        response = self.client.get(reverse('pesticides:about'))
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/about.html')
        html = response.content.decode()
        for anchor in ('id="pur"', 'id="spraydays"', 'id="prop65"', 'id="iarc"', 'id="tac"', 'id="categories"'):
            assert anchor in html
        assert 'one to two years after the fact' in html and '2023' in html

    def test_home_teaser_links_to_about(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert reverse('pesticides:about') + '#pur' in html
        assert 'id="pur"' not in html
