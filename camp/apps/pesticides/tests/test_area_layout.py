import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


def side(html):
    """The skeleton's left column's inner HTML."""
    match = re.search(r'<div class="column is-3-desktop tab-side">(.*?)</div>\s*<div class="column tab-map">', html, re.S)
    assert match, 'no filters row'
    return match.group(1)


class AreaTabLayoutTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def get(self, tab, **params):
        return self.client.get(self.fresno.get_pesticides_tab_url(tab), params).content.decode()

    def test_records_filters_beside_the_map_table_below(self):
        html = self.get('records')
        assert 'records-filters' in side(html)
        assert html.index('tab-side') < html.index('class="column tab-map"') < html.index('class="tab-table')
        assert 'records-filters' not in html[html.index('class="tab-table'):]

    def test_no_filters_beside_the_table(self):
        html = self.get('records')
        assert 'tab_has_filters' not in html
        table = html[html.index('class="tab-table'):]
        assert 'is-3-desktop' not in table.split('tab-charts')[0]
