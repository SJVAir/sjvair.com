import re
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.pesticides.views import NoticeList, RecordsBrowser
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

    def test_clamps_land_on_a_real_page(self):
        pages = [
            (reverse('pesticides:records'), RecordsBrowser),
            (reverse('pesticides:notice-list'), NoticeList),
            (Region.objects.get(pk=9001).get_pesticides_tab_url('records'), RecordsBrowser),
        ]
        for url, view in pages:
            with mock.patch.object(view, 'paginate_by', 1):
                last = self.client.get(url).context['paginator'].num_pages
                assert last > 1, url
                assert self.client.get(url, {'page': '99'}).context['page_obj'].number == last, url
                for page in ('nope', '-1'):
                    assert self.client.get(url, {'page': page}).context['page_obj'].number == 1, (url, page)


class EmptyTableSpanTests(RollupTestMixin, TestCase):
    """The "nothing matches" row spans exactly the header's columns."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def check(self, url, params, message):
        html = self.client.get(url, params).content.decode()
        head = html[html.index('<thead>'):html.index('</thead>')]
        body = html[html.index('<tbody>'):html.index('</tbody>')]
        assert message in body, (url, params)
        spans = re.findall(r'<td colspan="(\d+)"', body)
        assert spans == [str(len(re.findall(r'<th[ >]', head)))], (url, params, spans, len(re.findall(r'<th[ >]', head)))

    def test_records(self):
        self.check(reverse('pesticides:records'), {'chemical': 'nope'}, 'No records match.')
        self.check(reverse('pesticides:records'), {'county': 'fresno', 'chemical': 'nope'}, 'No records match.')
        self.check(self.fresno.get_pesticides_tab_url('records'), {'chemical': 'nope'}, 'No records match.')

    def test_notices(self):
        self.check(reverse('pesticides:notice-list'), {'chemical': 'nope'}, 'No notices match.')
        self.check(reverse('pesticides:notice-list'), {'county': 'fresno', 'chemical': 'nope'}, 'No notices match.')
        self.check(self.fresno.get_pesticides_tab_url('notices'), {'chemical': 'nope'}, 'No notices match.')
