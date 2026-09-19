from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, PesticideNotice
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class NoticeListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:notice-list')

    def test_active_default(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert [n.pk for n in response.context['object_list']] == [2, 3]
        assert response.context['mode'] == 'active'

    def test_filters(self):
        assert [n.pk for n in self.client.get(self.url, {'county': 'kern'}).context['object_list']] == [3]
        chem = Chemical.objects.get(pk=1)
        assert [n.pk for n in self.client.get(self.url, {'chemical': chem.sqid}).context['object_list']] == [3]

    def test_archive(self):
        response = self.client.get(self.url, {'past': 1})
        assert response.context['mode'] == 'past'
        assert [n.pk for n in response.context['object_list']] == [1]
        assert response.context['archive_months'][0]['year'] == 2020
        assert [n.pk for n in self.client.get(self.url, {'past': 1, 'archive_year': 2020, 'month': 1}).context['object_list']] == [1]
        # `object_list` in a paginated ListView's context is a (lazy) sliced
        # QuerySet, not a plain list -- QuerySet.__eq__ falls back to object
        # identity, so `queryset == []` is always False even when empty.
        # list(...) forces evaluation for a real comparison.
        assert list(self.client.get(self.url, {'past': 1, 'archive_year': 2020, 'month': 2}).context['object_list']) == []

    def test_archive_months_only_built_for_the_archive(self):
        assert self.client.get(self.url).context['archive_months'] == []

    def test_out_of_range_archive_year_is_ignored_not_a_500(self):
        for params in (
            {'past': 1, 'year': 9999},
            {'past': 1, 'archive_year': 9999},
            {'past': 1, 'archive_year': -5},
            {'past': 1, 'archive_year': 9999, 'month': 1},
        ):
            response = self.client.get(self.url, params)
            assert response.status_code == 200, params
            assert [n.pk for n in response.context['object_list']] == [1], params

    def test_archive_filter_form_carries_year_and_month(self):
        html = self.client.get(
            self.url, {'past': 1, 'archive_year': 2020, 'month': 1, 'county': 'fresno'},
        ).content.decode()
        assert '<input type="hidden" name="archive_year" value="2020">' in html
        assert '<input type="hidden" name="month" value="1">' in html

    def test_no_year_picker_in_active_mode(self):
        html = self.client.get(self.url).content.decode()
        assert 'class="year-picker"' not in html

    def test_spraydays_link_present(self):
        assert 'spraydays.cdpr.ca.gov' in self.client.get(self.url).content.decode()


class NoticeListYearContextTests(RollupTestMixin, TestCase):
    """`?year=` steers the nav links here, but never the (absent) year picker."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:notice-list')

    def test_nav_links_keep_the_year_param_without_a_year_picker(self):
        html = self.client.get(self.url, {'year': 2022}).content.decode()
        assert reverse('pesticides:records') + '?year=2022' in html
        assert 'class="year-picker"' not in html


class NoticeDetailTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_renders_active(self):
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        notice = PesticideNotice.objects.get(pk=2)
        response = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid}))
        assert response.status_code == 200
        ctx = response.context
        assert ctx['is_active'] is True
        assert (ctx['window_end'] - notice.scheduled_application).days == 4
        assert ctx['map_config']['center'] == '36.7100,-119.7900' and ctx['map_config']['zoom'] == 13
        html = response.content.decode()
        assert 'may begin any time through' in html and 'spraydays.cdpr.ca.gov' in html
        assert Chemical.objects.get(pk=2).get_absolute_url() in html
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html

    def test_past_notice(self):
        notice = PesticideNotice.objects.get(pk=1)
        ctx = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})).context
        assert ctx['is_active'] is False

    def test_404(self):
        assert self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': 'nope'})).status_code == 404


class EntityPageLinksTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_entity_page_links_to_its_records(self):
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(chem.get_absolute_url())
        assert 'recent_uses' not in response.context
        html = response.content.decode()
        assert reverse('pesticides:records') + f'?chemical={chem.sqid}' in html
        assert reverse('pesticides:notice-list') + f'?chemical={chem.sqid}' in html
