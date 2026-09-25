from django.core.cache import cache
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from camp.apps.pesticides import views
from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideUseRollup, PesticideUseTotal, Product, ProductChemical,
)
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


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
        assert response.context['scope_qs'] == '?year=2022'
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('SULFUR', 400.0), ('GLYPHOSATE', 80.0), ('CHLORPYRIFOS', 60.0),
        ]
        html = response.content.decode()
        assert Chemical.objects.get(pk=1).get_absolute_url() + '?year=2022' in html
        assert 'year=2022' in html and 'aria-current="page"' in html

    def test_unknown_year_falls_back_to_latest(self):
        response = self.client.get(self.url, {'year': '1999'})
        assert response.context['year'] == 2023
        assert response.context['scope_qs'] == ''

    def test_movers_defaults_to_the_previous_year(self):
        response = self.client.get(reverse('pesticides:home'), {'year': '2023'})
        movers = response.context['movers']
        assert movers['year_from'] == 2022
        assert movers['year_to'] == 2023
        assert movers['rising'] or movers['falling']

    def test_movers_follows_an_explicit_compare_year(self):
        response = self.client.get(reverse('pesticides:home'), {'year': '2022', 'compare': '2023'})
        movers = response.context['movers']
        assert movers['year_from'] == 2023
        assert movers['year_to'] == 2022

    def test_movers_is_absent_without_a_comparable_year(self):
        # 2022 is the earliest loaded year, so there is nothing before it.
        response = self.client.get(reverse('pesticides:home'), {'year': '2022'})
        assert response.context['movers'] is None
        assert 'Biggest movers' not in response.content.decode()

    def test_movers_is_absent_for_all_years(self):
        response = self.client.get(reverse('pesticides:home'), {'year': 'all'})
        assert response.context['movers'] is None

    def test_movers_renders_signed_changes(self):
        html = self.client.get(reverse('pesticides:home'), {'year': '2023'}).content.decode()
        assert 'Biggest movers' in html
        assert '2022 to 2023' in html
        assert 'Rose most' in html and 'Fell most' in html

    def test_compare_picker_offers_every_other_loaded_year(self):
        html = self.client.get(self.url, {'year': '2023'}).content.decode()
        assert 'data-scope="compare"' in html
        assert 'compare=2022' in html
        # Never itself: comparing a year to itself is not a mode.
        assert 'compare=2023' not in html

    def test_compare_picker_is_absent_under_all_years(self):
        html = self.client.get(self.url, {'year': 'all'}).content.decode()
        assert 'data-scope="compare"' not in html

    def test_all_years_link_clears_the_comparison(self):
        html = self.client.get(self.url, {'year': '2023', 'compare': '2022'}).content.decode()
        # The two are mutually exclusive, so the link mustn't carry compare on.
        assert 'href="?year=all"' in html

    def test_compare_rides_in_the_scope(self):
        response = self.client.get(self.url, {'year': '2023', 'compare': '2022'})
        assert response.context['compare'] == 2022
        assert response.context['compare_label'] == '2022 to 2023'
        assert response.context['compare_options'] == [2022]
        assert response.context['scope_qs'] == '?compare=2022'

    def test_compare_is_dropped_when_it_cannot_apply(self):
        # All years has no second term, and a year with no rollup is not a
        # comparison. Both leave the scope untouched.
        for params in ({'year': 'all', 'compare': '2022'}, {'year': '2023', 'compare': '1999'}):
            response = self.client.get(self.url, params)
            assert response.context['compare'] is None
            assert response.context['compare_label'] == ''
            assert 'compare=' not in response.context['scope_qs']

    def test_compare_pins_links_to_both_years(self):
        response = self.client.get(self.url, {'year': '2022', 'compare': '2023'})
        assert response.context['scope_qs'] == '?year=2022&compare=2023'
        html = response.content.decode()
        # Autoescaped in the markup, as any multi-parameter scope is.
        assert Chemical.objects.get(pk=1).get_absolute_url() + '?year=2022&amp;compare=2023' in html

    def test_all_years_sums_every_loaded_year(self):
        response = self.client.get(self.url, {'year': 'all'})
        assert response.context['all_years'] is True
        assert response.context['year'] is None
        assert response.context['year_label'] == '2022\u20132023'
        assert response.context['scope_qs'] == '?year=all'
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('SULFUR', 900.0), ('GLYPHOSATE', 260.0), ('CHLORPYRIFOS', 120.0),
        ]
        assert response.context['summary_sentence'] == '3 chemicals used 2022\u20132023'
        html = response.content.decode()
        assert 'Lbs applied' in html  # the year lives in the summary line, not the column header
        # The scope bar's year picker shows "All years" as the current choice.
        assert 'aria-current="page">All years</a>' in html
        assert Chemical.objects.get(pk=1).get_absolute_url() + '?year=all' in html

    def test_all_years_with_a_county(self):
        response = self.client.get(self.url, {'year': 'all', 'county': 'kern'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('CHLORPYRIFOS', 100.0), ('GLYPHOSATE', 30.0),
        ]
        assert response.context['summary_sentence'] == '2 chemicals used in Kern County 2022\u20132023'

    def test_scope_pickers_show_the_resolved_scope(self):
        html = self.client.get(self.url).content.decode()
        assert '<span class="explorer-scope-label">2023</span>' in html
        assert '<span class="explorer-scope-label">All counties</span>' in html
        assert 'aria-current="page">2023</a>' in html
        html = self.client.get(self.url, {'year': 'all', 'county': 'kern'}).content.decode()
        assert '<span class="explorer-scope-label">All years</span>' in html
        assert '<span class="explorer-scope-label">Kern</span>' in html
        assert 'aria-current="page">Kern</a>' in html
        # Switching one keeps the other; the filter form carries both as hidden inputs.
        assert 'href="?year=2022&amp;county=kern"' in html
        assert 'href="?year=all&amp;county=fresno"' in html
        assert '<input type="hidden" name="year" value="all">' in html
        assert '<input type="hidden" name="county" value="kern">' in html

    def test_short_county_names_where_the_label_already_says_county(self):
        kern = Region.objects.get(slug='kern')
        assert kern.short_name == 'Kern' and kern.name == 'Kern County'
        html = self.client.get(reverse('pesticides:records'), {'county': 'kern'}).content.decode()
        # Table cells and the picker drop "County"; the summary sentence keeps it.
        assert '>Kern</a>' in html
        assert 'Kern County' in html.split('summary-sentence')[1][:200]

    def test_placeholder_chemicals_stay_out_of_the_list_and_explain_themselves(self):
        placeholder = Chemical.objects.create(chem_code=-2, name='AI IS CONFIDENTIAL')
        assert placeholder.is_placeholder and not Chemical.objects.get(pk=1).is_placeholder
        html = self.client.get(self.url, {'year': 'all'}).content.decode()
        assert 'AI IS CONFIDENTIAL' not in html
        response = self.client.get(placeholder.get_absolute_url())
        assert response.status_code == 200
        html = response.content.decode()
        assert 'shorthand for active ingredient' in html
        assert response.context['hide_lbs'] is True
        assert 'Lbs applied' not in html

    def test_county_scope_is_left_off_pages_narrower_than_a_county(self):
        region = Region.objects.get(pk=9001)
        html = self.client.get(reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': region.slug}), {'county': 'kern'}).content.decode()
        assert 'data-scope="year"' in html
        assert 'data-scope="county"' not in html
        # The scope still rides along in the page's links.
        assert 'county=kern' in html

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

    def test_related_filter_is_scoped_to_the_year(self):
        # Sulfur shared records with LORSBAN only in 2022: the 2023 list under
        # that product filter leaves sulfur out rather than showing a dash.
        PesticideUseRollup.objects.create(year=2022, month=1, county_id=9001, chemical_id=3, product_id=2, lbs_chemical=5, applications=1)
        product = Product.objects.get(pk=2)
        assert self.names(self.client.get(self.url, {'product': product.sqid, 'year': '2023'})) == ['CHLORPYRIFOS']
        assert set(self.names(self.client.get(self.url, {'product': product.sqid, 'year': '2022'}))) == {'CHLORPYRIFOS', 'SULFUR'}
        assert set(self.names(self.client.get(self.url, {'product': product.sqid, 'year': 'all'}))) == {'CHLORPYRIFOS', 'SULFUR'}

    def test_related_filter_relabels_the_columns(self):
        product = Product.objects.get(pk=2)
        html = self.client.get(self.url, {'product': product.sqid}).content.decode()
        assert 'Lbs via LORSBAN 4E' in html
        assert 'sort=-products' not in html  # the Products column header (the nav tab stays)
        plain = self.client.get(self.url).content.decode()
        assert 'Lbs applied' in plain and 'sort=-products' in plain

    def test_related_filter_shows_the_pairs_pounds(self):
        # Filtered to a product, the pounds column is that product's share
        # of the chemical's pounds, not the chemical's total.
        product = Product.objects.get(pk=2)
        # Some chlorpyrifos applied through another product, so the pair and the total differ.
        PesticideUseRollup.objects.create(year=2023, month=1, county_id=9001, chemical_id=2, product_id=1, lbs_chemical=25, applications=1)
        response = self.client.get(self.url, {'product': product.sqid})
        chemical = response.context['object_list'][0]
        pair = PesticideUseRollup.objects.filter(year=2023, chemical=chemical, product=product).aggregate(Sum('lbs_chemical'))
        total = PesticideUseRollup.objects.filter(year=2023, chemical=chemical).aggregate(Sum('lbs_chemical'))
        assert chemical.lbs_applied == pair['lbs_chemical__sum'] == 60.0
        assert total['lbs_chemical__sum'] == 85.0

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

    def test_detail_page_has_the_section_map_filtered_to_the_chemical(self):
        html = self.client.get(self.chemical.get_absolute_url() + '?year=2022').content.decode()
        assert f'data-chemical="{self.chemical.chem_code}"' in html
        assert 'data-year="2022"' in html
        assert 'data-show-notices="0"' in html
        assert f'/tools/pesticides/map/?chemical={self.chemical.sqid}&amp;year=2022' in html
        # The latest year needs no param.
        latest = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert f'/tools/pesticides/map/?chemical={self.chemical.sqid}"' in latest

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
        # The scope carries over (the map's popup links arrive this way).
        response = self.client.get(reverse('pesticides:chemical-redirect', kwargs={'sqid': self.chemical.sqid}), {'year': 2022, 'county': 'kern'})
        assert response['Location'] == self.chemical.get_absolute_url() + '?year=2022&county=kern'

    def test_bad_sqid_404(self):
        assert self.client.get('/tools/pesticides/chemicals/nope/x/').status_code == 404
        assert self.client.get('/tools/pesticides/chemicals/nope/').status_code == 404

    def test_trend_chart_above_the_by_year_table(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'class="explorer-chart trend-chart"' in html
        assert 'class="chart-canvas" data-chart="chart-' in html
        # 2023: 180 lbs against 2022's 80. The first loaded year is the
        # previous one here, so it isn't repeated.
        assert 'Up 125% since 2022' in html
        assert html.index('trend-chart') < html.index('by-year-table')

    def test_trend_chart_under_all_years(self):
        html = self.client.get(self.chemical.get_absolute_url(), {'year': 'all'}).content.decode()
        assert 'class="explorer-chart trend-chart"' in html
        assert 'Up 125% since 2022' in html

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
        # Honest count with the current implementation is 26 (verified
        # query-by-query: every related-object fetch is batched via
        # in_bulk/prefetch/select_related, no N+1s -- 18 base queries
        # (including the by_month rollup aggregate for the future month
        # chart) plus the county map's geometry build, the by-county
        # region-name lookup, the by-county-table's in_bulk() for
        # county_sqid, the available-years lookup for the year picker, and
        # the county list for the county picker; all cached after the first
        # request). The last three are the movers card: one group-by per
        # direction and one in_bulk for the regions, a fixed cost that
        # doesn't grow with the number of movers shown.
        with self.assertNumQueries(26):
            self.client.get(self.chemical.get_absolute_url())

    def test_by_month_in_context(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert len(ctx['by_month']) == 12
        assert ctx['by_month'][2]['lbs'] == 100.0

    def test_county_map_rendered(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'class="map-figure"' in html
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

    def test_trend_chart_on_the_landing_page(self):
        response = self.client.get(self.url)
        assert [(r['year'], r['lbs']) for r in response.context['by_year']] == [(2023, 740.0), (2022, 540.0)]
        html = response.content.decode()
        assert 'class="explorer-chart trend-chart"' in html
        assert 'Lbs applied by year' in html
        assert 'Up 37% since 2022' in html

    def test_trend_chart_follows_the_county_scope(self):
        response = self.client.get(self.url, {'county': 'kern'})
        assert [(r['year'], r['lbs']) for r in response.context['by_year']] == [(2023, 70.0), (2022, 60.0)]

    def test_leaderboards_link_to_details(self):
        html = self.client.get(self.url).content.decode()
        assert Chemical.objects.get(pk=3).get_absolute_url() in html
        assert Commodity.objects.get(pk=2).get_absolute_url() in html

    def test_explorer_region_is_boosted(self):
        html = self.client.get(self.url).content.decode()
        assert 'id="explorer"' in html
        assert 'hx-boost="true"' in html
        # Only the body swaps; the hero's tabs refresh out of band. The scope
        # bar is inside the body, so it swaps with the page it describes.
        assert 'hx-target="#explorer-body"' in html
        assert 'hx-select-oob="#explorer-tabs"' in html
        assert 'id="explorer-body"' in html and 'id="explorer-tabs"' in html
        assert html.index('id="explorer-body"') < html.index('class="explorer-scope-pickers"')
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

    def test_has_entity_pickers_and_carries_the_scope(self):
        html = self.client.get(self.url).content.decode()
        assert html.index('data-kind="product"') < html.index('data-kind="chemical"') < html.index('data-kind="commodity"')
        # The county is the explorer's scope, picked in the scope bar, not a toolbar filter.
        assert 'name="county"' not in html.split('class="map-toolbar-filters"')[1].split('</form>')[0]
        chemical = Chemical.objects.get(pk=1)
        html = self.client.get(self.url, {'chemical': chemical.sqid, 'county': 'fresno', 'year': '2022'}).content.decode()
        assert 'Glyphosate <button type="button" class="delete is-small entity-picker-clear"' in html
        assert '<input type="hidden" name="year" value="2022">' in html
        assert '<input type="hidden" name="county" value="fresno">' in html
        assert 'Fresno</span>' in html

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
        assert 'class="section-map map-canvas"' in html and 'data-year="2023"' in html
        assert 'data-counties-url="/api/2.0/pesticides/counties/"' in html
        assert 'data-townships-url="/api/2.0/pesticides/townships/"' in html
        # Popup links are built client-side from these URL patterns.
        assert 'data-product-page-url="/tools/pesticides/products/{id}/"' in html
        assert 'data-notice-page-url="/tools/pesticides/notices/{id}/"' in html
        assert html.index('js/maps/registry.js') < html.index('js/pesticides/section-map.js')
        assert '<noscript>' in html and 'class="map-figure"' in html   # static fallback

    def test_section_map_renders_through_the_shared_include(self):
        html = self.client.get(self.url).content.decode()
        assert 'class="map-wrap"' in html
        assert 'class="section-map map-canvas" id="section-map-2023"' in html
        # The page's filters, then Options (the metric and layer toggles), then Expand.
        assert html.index('class="map-toolbar-filters"') < html.index('map-options') < html.index('class="button map-expand"')
        assert 'name="metric"' in html and 'class="section-map-controls"' in html
        # The legend body's hooks for the script, and the toggle pointing at it.
        assert 'aria-controls="section-map-2023-legend"' in html and 'id="section-map-2023-legend"' in html
        assert 'class="county-legend section-map-legend"' in html
        # The map frames itself on the counties: no shared bounds.
        assert 'data-bounds=""' in html
        # The chrome the page rendered, for the script (which trusts this
        # over the map module's spec).
        assert 'data-features="expand legend status toolbar"' in html
        assert 'class="map-status"' in html

    def test_only_the_map_page_has_the_filter_toolbar(self):
        config = views.section_map_config(2023)
        assert config['map']['toolbar_template'] is None
        assert config['map']['options_template'] == 'pesticides/includes/map-options.html'
        assert config['map']['features'] == {'toolbar': True, 'expand': True, 'legend': True, 'status': True}
        assert views.section_map_config(2023, toolbar=True)['map']['toolbar_template'] == 'pesticides/includes/map-toolbar.html'

    def test_every_flat_key_is_a_data_attribute(self):
        config = views.section_map_config(2023, chemical=None, show_locations=True)
        data = config['map']['data']
        for key, value in config.items():
            if key == 'map':
                continue
            assert data[key.replace('_', '-')] == ('' if value is None else str(value))

    @override_settings(MAPTILER_API_KEY='test-key')
    def test_map_reads_its_key_and_style_from_the_container(self):
        # The MapTiler SDK map takes the API key and a style id straight off
        # the container; there's no raster tile template.
        response = self.client.get(self.url)
        cfg = response.context['map_config']
        assert cfg['maptiler_key'] == 'test-key'
        assert cfg['style'] == 'dataviz'
        # The SDK style carries its own attribution; there's no template
        # or attribution text to pass.
        assert 'tile_url' not in cfg
        assert 'attribution' not in cfg
        html = response.content.decode()
        # The section map's own container (the noscript county choropleth
        # has the same attributes, so it's picked out by class).
        start = html.index('class="section-map map-canvas"')
        container = html[start:html.index('>', start)]
        assert 'data-maptiler-key="test-key"' in container
        assert 'data-style="dataviz"' in container
        assert 'data-tiles=' not in container
        assert 'data-gl=' not in container
        assert 'data-attribution=' not in container

    def test_page_loads_the_sdk_and_no_leaflet(self):
        html = self.client.get(self.url).content.decode()
        # The shared map chrome's stylesheet, before the section map's own.
        assert html.index('css/maps/map.css') < html.index('css/pesticides/section-map.css')
        assert 'maptiler-sdk/maptiler-sdk.js' in html
        assert 'maptiler-sdk/maptiler-sdk.css' in html
        assert html.count('js/pesticides/section-map') == 1   # one map module, no spike beside it
        # The static county choropleth (includes/county-map.html) draws on
        # the SDK too, through the map figure module, loaded after the SDK.
        assert 'js/admin/map-figure.js' in html
        assert 'js/admin/map-figure.css' in html
        assert html.index('maptiler-sdk/maptiler-sdk.js') < html.index('js/admin/map-figure.js')
        assert html.index('js/maps/registry.js') < html.index('js/admin/map-figure.js')
        assert html.count('js/maps/core.js') == 1
        assert 'leaflet' not in html.lower()

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

    def test_school_markers_are_off_by_default(self):
        response = self.client.get(self.url)
        assert response.context['map_config']['show_locations'] == '0'
        html = response.content.decode()
        assert 'data-show-locations="0"' in html
        assert 'data-locations-url="/api/2.0/pesticides/locations/"' in html
        assert 'name="locations" checked' not in html

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


# The commodity list's query count under `?year=all&concern=1`; it must not
# grow with the number of commodities on the page (see the test below).
CONCERN_COMMODITY_QUERIES = 9


class ConcernScopeTests(RollupTestMixin, TestCase):
    """
    `?concern=1` as an explorer-wide scope. GLYPHOSATE and CHLORPYRIFOS are
    of concern in the fixture; SULFUR (and SULFUR DUST, its only product)
    are not, and they carry most of the pounds.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_chemical_list_narrows_and_counts_concern_pounds(self):
        response = self.client.get(reverse('pesticides:chemical-list'), {'concern': '1'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('GLYPHOSATE', 180.0), ('CHLORPYRIFOS', 60.0),
        ]
        assert response.context['concern'] is True
        assert response.context['scope_qs'] == '?concern=1'
        assert 'of concern' in response.context['summary_sentence']

    def test_product_list_keeps_products_with_a_concern_chemical(self):
        response = self.client.get(reverse('pesticides:product-list'), {'concern': '1'})
        assert [(p.name, p.lbs_applied) for p in response.context['object_list']] == [
            ('LORSBAN 4E', 135.0), ('ROUNDUP PRO', 450.0),
        ]

    def test_commodity_list_counts_concern_pounds_only(self):
        response = self.client.get(reverse('pesticides:commodity-list'), {'concern': '1'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('ALMOND', 150.0), ('GRAPE', 50.0), ('COTTON', 40.0),
        ]

    def test_landing_page_totals_narrow(self):
        response = self.client.get(reverse('pesticides:home'), {'concern': '1'})
        assert response.context['total_lbs'] == 240.0
        assert response.context['concern'] is True
        assert [r.obj.name for r in response.context['top_chemicals']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert 'top_chemicals_of_concern' not in response.context

    def test_commodity_page_counts_concern_pounds_only(self):
        grape = Commodity.objects.get(name='GRAPE')
        response = self.client.get(grape.get_absolute_url(), {'concern': '1'})
        assert response.context['totals']['lbs'] == 50.0
        assert [r.obj.name for r in response.context['related_a']['rows']] == ['GLYPHOSATE']
        assert response.context['concern_excluded'] is False

    def test_chemical_page_not_of_concern_says_so_and_stays_unscoped(self):
        sulfur = Chemical.objects.get(name='SULFUR')
        response = self.client.get(sulfur.get_absolute_url(), {'concern': '1'})
        assert response.context['concern_excluded'] is True
        assert response.context['totals']['lbs'] == 500.0

    def test_chemical_page_of_concern_is_not_excluded(self):
        glyphosate = Chemical.objects.get(name='GLYPHOSATE')
        response = self.client.get(glyphosate.get_absolute_url(), {'concern': '1'})
        assert response.context['concern_excluded'] is False
        assert response.context['totals']['lbs'] == 180.0

    def test_section_page_totals_narrow(self):
        section = Region.objects.get(pk=9101)
        url = reverse('pesticides:section-detail', kwargs={'sqid': section.sqid})
        assert self.client.get(url).context['totals']['lbs'] == 670.0
        response = self.client.get(url, {'concern': '1'})
        assert response.context['totals']['lbs'] == 170.0
        assert response.context['concern'] is True

    def test_county_choropleth_is_scoped_and_keeps_the_scope_in_its_links(self):
        fresno = Region.objects.get(pk=9001)
        county_url = reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'})
        for url in (reverse('pesticides:home'), reverse('pesticides:map'), reverse('pesticides:records')):
            html = self.client.get(url, {'concern': '1'}).content.decode()
            assert 'Fresno County: 170 lbs' in html, url
            assert f'{county_url}?concern=1' in html, url

    def test_detail_page_county_links_keep_the_scope(self):
        glyphosate = Chemical.objects.get(name='GLYPHOSATE')
        fresno = Region.objects.get(pk=9001)
        html = self.client.get(glyphosate.get_absolute_url(), {'concern': '1'}).content.decode()
        assert reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'}) + '?concern=1' in html

    def test_map_page_passes_the_scope_to_the_grid(self):
        response = self.client.get(reverse('pesticides:map'), {'concern': '1'})
        assert response.context['map_config']['concern'] == '1'
        assert self.client.get(reverse('pesticides:map')).context['map_config']['concern'] == ''

    def test_scope_bar_toggle_reflects_and_flips_the_scope(self):
        url = reverse('pesticides:chemical-list')
        html = self.client.get(url).content.decode()
        assert 'explorer-scope-toggle' in html
        assert 'Chemicals of concern' in html
        assert 'data-tooltip="Prop 65, CARB toxic air contaminants, IARC 1/2A/2B"' in html
        assert 'explorer-scope-toggle is-set' not in html
        assert 'aria-pressed="false"' in html
        assert 'href="?concern=1"' in html

        html = self.client.get(url, {'concern': '1'}).content.decode()
        assert 'explorer-scope-toggle is-set' in html
        assert 'aria-pressed="true"' in html
        assert 'role="button"' in html
        # Turning it off clears the param, keeping the rest of the scope. With
        # nothing left in the query string the link is the bare path.
        assert f'href="{url}"' in html
        html = self.client.get(url, {'concern': '1', 'county': 'kern'}).content.decode()
        assert 'href="?county=kern"' in html

    def test_filter_forms_carry_the_scope_as_a_hidden_input(self):
        html = self.client.get(reverse('pesticides:chemical-list'), {'concern': '1'}).content.decode()
        assert '<input type="hidden" name="concern" value="1">' in html
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert 'name="concern"' not in html

    def test_map_template_carries_the_scope_as_a_data_attribute(self):
        html = self.client.get(reverse('pesticides:map'), {'concern': '1'}).content.decode()
        assert 'data-concern="1"' in html
        html = self.client.get(reverse('pesticides:map')).content.decode()
        assert 'data-concern=""' in html

    def test_landing_leaderboard_titles_follow_the_scope(self):
        # Unscoped: a chemicals board and a dedicated of-concern board.
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert html.count('Most applied chemicals of concern') == 1
        assert html.count('Most applied chemicals ·') == 1
        # Scoped: one board, and its title says what it now is.
        html = self.client.get(reverse('pesticides:home'), {'concern': '1'}).content.decode()
        assert html.count('Most applied chemicals of concern') == 1
        assert 'Most applied chemicals ·' not in html

    def test_scope_banner_says_the_numbers_are_concern_only(self):
        url = reverse('pesticides:chemical-list')
        banner = 'Showing chemicals of concern only'
        assert banner not in self.client.get(url).content.decode()
        html = self.client.get(url, {'concern': '1'}).content.decode()
        assert banner in html
        assert 'Show all chemicals' in html

    def test_about_page_defines_the_scope_and_hides_the_toggle(self):
        html = self.client.get(reverse('pesticides:about')).content.decode()
        assert 'id="concern"' in html
        assert 'explorer-scope-toggle' not in html
        assert 'explorer-scope-pickers' not in html
        # And the toggle links to that definition where it does render.
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert reverse('pesticides:about') + '#concern' in html

    def test_banner_stays_off_a_page_the_scope_cant_narrow(self):
        # The page renders unscoped and says why; a banner claiming the
        # numbers are concern-only would contradict its own note.
        sulfur = Chemical.objects.get(name='SULFUR')
        html = self.client.get(sulfur.get_absolute_url(), {'concern': '1'}).content.decode()
        assert 'Showing chemicals of concern only' not in html
        assert "so the chemicals-of-concern scope doesn't narrow this page" in html
        # It's still there on a page the scope does narrow.
        glyphosate = Chemical.objects.get(name='GLYPHOSATE')
        html = self.client.get(glyphosate.get_absolute_url(), {'concern': '1'}).content.decode()
        assert 'Showing chemicals of concern only' in html

    def test_product_page_without_a_concern_chemical_explains_itself(self):
        dust = Product.objects.get(name='SULFUR DUST')
        response = self.client.get(dust.get_absolute_url(), {'concern': '1'})
        assert response.context['concern_excluded'] is True
        # Rendered unscoped rather than blanked to zeros.
        assert response.context['totals']['lbs'] == 550.0
        html = response.content.decode()
        assert "None of this product's active ingredients is on the Prop 65" in html
        assert 'Show all chemicals' in html

    def test_product_page_active_ingredients_ignore_the_scope(self):
        # What a product is made of is a registration fact, not a scoped one.
        roundup = Product.objects.get(name='ROUNDUP PRO')
        response = self.client.get(roundup.get_absolute_url(), {'concern': '1'})
        assert response.context['concern_excluded'] is False
        assert [r.obj.name for r in response.context['related_a']['rows']] == ['GLYPHOSATE']

    def test_commodity_page_without_concern_use_explains_itself(self):
        # In 2022 GRAPE carries sulfur only.
        grape = Commodity.objects.get(name='GRAPE')
        response = self.client.get(grape.get_absolute_url(), {'concern': '1', 'year': '2022'})
        assert response.context['concern_excluded'] is True
        assert response.context['totals']['lbs'] == 400.0
        assert 'No chemical of concern was reported on this commodity' in response.content.decode()

    def test_excluded_chemical_page_explains_itself(self):
        sulfur = Chemical.objects.get(name='SULFUR')
        note = "so the chemicals-of-concern scope doesn't narrow this page"
        html = self.client.get(sulfur.get_absolute_url(), {'concern': '1'}).content.decode()
        assert note in html
        html = self.client.get(sulfur.get_absolute_url()).content.decode()
        assert note not in html

    def test_commodity_list_all_years_concern_pounds_come_from_one_group_by(self):
        # The pounds column under `?year=all&concern=1` used to be a
        # correlated sum over the rollup, run once per commodity on the page;
        # it now comes from one cached group-by (stats.commodity_concern_lbs),
        # so the page's query count doesn't grow with the number of rows.
        url = reverse('pesticides:commodity-list')
        response = self.client.get(url, {'year': 'all', 'concern': '1'})
        assert [(c.name, c.lbs_applied) for c in response.context['object_list']] == [
            ('ALMOND', 230.0), ('COTTON', 100.0), ('GRAPE', 50.0),
        ]
        cache.clear()
        with self.assertNumQueries(CONCERN_COMMODITY_QUERIES):
            self.client.get(url, {'year': 'all', 'concern': '1'})
        for index in range(4, 9):
            Commodity.objects.create(site_code=f'800{index}', name=f'CROP {index}')
        cache.clear()
        with self.assertNumQueries(CONCERN_COMMODITY_QUERIES):
            self.client.get(url, {'year': 'all', 'concern': '1'})


class CompareReachesEveryMapTests(RollupTestMixin, TestCase):
    """
    Every page that draws the section map has to pass the compared year down
    to it, or the scope bar offers a comparison the map quietly ignores.
    One call site (places.place_context) was missed exactly that way, so this
    walks all of them rather than trusting a grep.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def map_pages(self):
        fresno = Region.objects.get(pk=9001)
        section = Region.objects.get(pk=9101)
        chemical = Chemical.objects.get(pk=1)
        return {
            'map': reverse('pesticides:map'),
            'records': reverse('pesticides:records'),
            'place': reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': fresno.slug}),
            'section': reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}),
            'chemical': chemical.get_absolute_url(),
            'near': reverse('pesticides:near-me'),
        }

    def test_every_map_page_carries_the_compared_year(self):
        missing = []
        for name, url in self.map_pages().items():
            params = {'year': '2023', 'compare': '2022'}
            if name == 'near':
                params.update({'lat': '36.71', 'lng': '-119.79', 'radius': '1'})
            html = self.client.get(url, params).content.decode()
            if 'section-map' not in html:
                continue
            if 'data-compare="2022"' not in html:
                missing.append(name)
        assert not missing, 'pages that dropped the compared year: %s' % ', '.join(missing)

    def test_no_compare_leaves_the_attribute_empty(self):
        for name, url in self.map_pages().items():
            params = {'year': '2023'}
            if name == 'near':
                params.update({'lat': '36.71', 'lng': '-119.79', 'radius': '1'})
            html = self.client.get(url, params).content.decode()
            if 'section-map' not in html:
                continue
            assert 'data-compare=""' in html, name
