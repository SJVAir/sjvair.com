from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class NearestPageTests(RollupTestMixin, TestCase):
    """A junk or out-of-range ?page= lands on a real page on every list."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        fresno = Region.objects.get(pk=9001)
        self.urls = [
            reverse('pesticides:product-list'),
            reverse('pesticides:chemical-list'),
            reverse('pesticides:commodity-list'),
            reverse('pesticides:records'),
            reverse('pesticides:notice-list'),
            fresno.get_pesticides_tab_url('records'),
            fresno.get_pesticides_tab_url('notices'),
        ]

    def test_bad_pages_are_not_404s(self):
        for url in self.urls:
            for page in ('99', 'nope', '-1', '0'):
                response = self.client.get(url, {'page': page})
                assert response.status_code == 200, (url, page)

    def test_records_pager_sits_after_the_table(self):
        html = self.client.get(reverse('pesticides:records')).content.decode()
        assert html.index('records-table') < html.rindex('</table>')
        if 'class="pagination' in html:
            assert html.rindex('</table>') < html.index('class="pagination')
