from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, Commodity, Product, ProductChemical


class ChemicalListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:chemical-list')

    def names(self, response):
        return [c.name for c in response.context['object_list']]

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/chemical-list.html')
        assert response.context['result_count'] == 3
        assert response.context['latest_year'] == 2023

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

    def test_pagination_links_keep_filters(self):
        for i in range(60):
            Chemical.objects.create(chem_code=10000 + i, name=f'TEST {i}', categories=['oil'])
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
