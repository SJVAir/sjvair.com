import re

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from camp.apps.pesticides.templatetags.pesticides_explorer import (
    chart_table, method_stack_chart, trend_chart,
)
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class ChartTableTests(SimpleTestCase):
    def test_trend_chart_numbers_are_in_a_table_for_screen_readers(self):
        rows = [{'year': 2023, 'lbs': 88.0}, {'year': 2022, 'lbs': 100.0}]
        html = render_to_string('pesticides/includes/trend-chart.html', trend_chart(rows, 2023))
        assert '<div class="is-sr-only">' in html
        assert '<th scope="row">2022</th><td>100</td>' in html
        assert '<th scope="row">2023</th><td>88</td>' in html

    def test_stacked_chart_has_a_column_per_series(self):
        stack = {'years': [2022, 2023], 'series': [
            {'method': 'G', 'label': 'Ground', 'values': [10, 20]},
            {'method': 'A', 'label': 'Air', 'values': [1, 2]},
        ]}
        table = chart_table(method_stack_chart(stack)['chart'])
        assert table['columns'] == ['Ground (lbs)', 'Air (lbs)']
        assert table['rows'] == [(2022, [10, 1]), (2023, [20, 2])]

    def test_chart_titles_are_headings(self):
        rows = [{'year': 2023, 'lbs': 88.0}]
        html = render_to_string('pesticides/includes/trend-chart.html', trend_chart(rows, 2023))
        assert '<h3 class="chart-title">Lbs applied by year</h3>' in html


class ExplorerMarkupTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def test_dropdowns_are_not_aria_menus(self):
        html = self.client.get(self.fresno.get_pesticides_tab_url('records')).content.decode()
        assert 'role="menu"' not in html and 'role="menuitem"' not in html
        assert 'aria-controls="scope-menu-year"' in html and 'id="scope-menu-year"' in html

    def test_one_h1_per_page(self):
        for url in (
            reverse('pesticides:home'),
            reverse('pesticides:notice-list'),
            reverse('pesticides:product-list'),
            self.fresno.get_pesticides_tab_url('records'),
        ):
            html = self.client.get(url).content.decode()
            assert len(re.findall(r'<h1[\s>]', html)) == 1, url

    def test_notice_mode_is_a_labelled_group(self):
        html = self.client.get(reverse('pesticides:notice-list')).content.decode()
        assert '<fieldset class="field notice-mode">' in html
        assert '<legend class="label">Notices</legend>' in html

    def test_sorted_header_says_so(self):
        html = self.client.get(reverse('pesticides:product-list'), {'sort': '-lbs'}).content.decode()
        assert re.search(r'<th class="has-text-right" aria-sort="descending">\s*<a class="sort-link is-active"', html)
        assert 'aria-sort="ascending"' not in html

    def test_map_options_button_is_named(self):
        html = self.client.get(reverse('pesticides:map')).content.decode()
        assert 'aria-label="Map options"' in html and 'role="dialog"' in html
        # The toolbar precedes the canvas (and so its attribution) in focus order.
        assert html.index('class="map-toolbar"') < html.index('map-canvas')

    def test_reveal_toggles_control_their_list(self):
        html = self.client.get(self.fresno.get_pesticides_tab_url('overview')).content.decode()
        for toggle in re.findall(r'<button[^>]*data-reveal-toggle[^>]*>', html):
            assert 'aria-controls="' in toggle


class PaginationTests(SimpleTestCase):
    def test_disabled_ends_are_not_links(self):
        from django.core.paginator import Paginator
        from django.test import RequestFactory
        page = Paginator(list(range(100)), 10).page(1)
        context = {'is_paginated': True, 'page_obj': page}
        html = render_to_string('pesticides/includes/pagination.html', context, request=RequestFactory().get('/'))
        assert '<span class="pagination-previous is-disabled" aria-disabled="true">Previous</span>' in html
        assert '<a class="pagination-previous"' not in html
