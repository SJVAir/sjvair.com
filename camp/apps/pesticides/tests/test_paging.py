from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.pesticides.views import RecordsBrowser
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
        with mock.patch.object(RecordsBrowser, 'paginate_by', 1):
            html = self.client.get(reverse('pesticides:records')).content.decode()
        assert 'class="pagination' in html
        table_end = html.rindex('</table>')
        pager = html.index('class="pagination')
        assert table_end < pager
        # Past the table-container's closing tag, so outside the include's wrapper.
        assert '</div>' in html[table_end:pager]
