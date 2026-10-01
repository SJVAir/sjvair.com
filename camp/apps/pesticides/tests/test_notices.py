from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import stats, views
from camp.apps.pesticides.models import Chemical, PesticideNotice
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Region


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

    def test_out_of_range_page_is_not_a_404(self):
        for page in ('99', 'nope'):
            assert self.client.get(self.url, {'page': page}).status_code == 200
            assert self.client.get(self.url, {'past': 1, 'page': page}).status_code == 200
        assert self.client.get(self.url, {'page': 'nope'}).context['page_obj'].number == 1

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

    def test_archive_months_count_what_the_page_shows(self):
        archived = PesticideNotice.objects.get(pk=1)
        own = self.client.get(self.url, {'past': 1, 'county': archived.county.slug}).context['archive_months']
        assert [(m['year'], m['month'], m['count']) for m in own] == [(2020, 1, 1)]
        # Another county's archive has nothing in that month, so no month at all.
        other = Region.objects.filter(type=Region.Type.COUNTY).exclude(pk=archived.county_id).first()
        assert self.client.get(self.url, {'past': 1, 'county': other.slug}).context['archive_months'] == []

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
        html = response.content.decode()
        assert 'may begin any time through' in html and 'spraydays.cdpr.ca.gov' in html
        assert Chemical.objects.get(pk=2).get_absolute_url() in html
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html

    def test_frames_the_section_not_the_point(self):
        # SprayDays only gives the square-mile section, so the map frames and
        # highlights it rather than centring a pin as if it were the field.
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        notice = PesticideNotice.objects.get(pk=2)
        response = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid}))
        config = response.context['map_config']
        assert config['highlight'] == notice.mtrs.sqid
        assert config['zoom'] == 13
        assert config['center'] == views.centroid(notice.mtrs)
        assert 'SprayDays gives the square-mile section, not the field' in response.content.decode()

    def test_without_a_section_falls_back_to_the_point(self):
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=None)
        notice = PesticideNotice.objects.get(pk=2)
        response = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid}))
        assert response.status_code == 200
        config = response.context['map_config']
        assert config['center'] == '36.7100,-119.7900' and config['zoom'] == 13
        assert not config.get('highlight')

    def test_past_notice(self):
        notice = PesticideNotice.objects.get(pk=1)
        ctx = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})).context
        assert ctx['is_active'] is False

    def test_scope_bar_matches_the_notices_list(self):
        # The toggle and the county picker render here as they do on the
        # list; the year picker doesn't apply to a scheduled notice.
        notice = PesticideNotice.objects.get(pk=2)
        url = reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})
        response = self.client.get(url)
        assert response.context['scope_concern'] is True
        assert 'year_options' not in response.context
        html = response.content.decode()
        assert 'data-scope="narrow"' in html
        assert 'Flagged chemicals' in html
        assert 'data-scope="county"' in html
        assert 'data-scope="year"' not in html
        # And it reflects the scope it was asked for.
        html = self.client.get(url, {'narrow': 'concern', 'county': 'kern'}).content.decode()
        assert 'aria-label="Narrow to: Flagged chemicals"' in html
        assert 'Showing flagged chemicals only' in html

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


class NoticeConcernScopeTests(TestCase):
    """`?narrow=concern` keeps only notices listing a chemical of concern."""

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:notice-list')

    def test_notices_without_a_concern_chemical_drop_out(self):
        sulfur = Chemical.objects.get(name='SULFUR')
        notice = PesticideNotice.objects.get(pk=2)
        notice.chemicals.set([sulfur])
        response = self.client.get(self.url, {'concern': '1'})
        assert [n.pk for n in response.context['object_list']] == [3]
        assert response.context['concern'] == stats.NARROW_CONCERN
        assert [n.pk for n in self.client.get(self.url).context['object_list']] == [2, 3]

    def test_a_notice_is_listed_once_even_with_several_concern_chemicals(self):
        # Notice 3 carries both GLYPHOSATE and CHLORPYRIFOS.
        response = self.client.get(self.url, {'concern': '1'})
        assert [n.pk for n in response.context['object_list']] == [2, 3]


class UpcomingNoticeLinkTests(TestCase):
    """
    Each row in the upcoming-notices box reaches its own notice, the way a row
    in the notices list does. Without it the box is a dead end: it names a
    scheduled application and offers no way to see the rest of it.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        # The fixture leaves the upcoming notices unplaced, so the section
        # page has none of its own to render.
        PesticideNotice.objects.filter(pk=2).update(mtrs_id=9101)

    def test_every_upcoming_page_links_each_notice(self):
        fresno = Region.objects.get(pk=9001)
        section = Region.objects.get(pk=9101)
        pages = {
            # A place's notices, day by day, are on its Notices tab.
            'place': reverse('pesticides:region-notices', kwargs={'sqid': fresno.sqid, 'slug': fresno.slug}),
            'section': reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}),
            'chemical': Chemical.objects.get(pk=1).get_absolute_url(),
        }
        for name, url in pages.items():
            response = self.client.get(url)
            upcoming = response.context.get('upcoming') or []
            assert upcoming, f'{name} has no upcoming notices to link'
            html = response.content.decode()
            for notice in upcoming:
                href = reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})
                assert href in html, f'{name} does not link notice {notice.pk}'


class AreaNoticesTabTests(TestCase):
    """The Notices tab: the notice list, narrowed to its place."""
    fixtures = ['pesticides-explorer']
    POINT = {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma'}

    def setUp(self):
        cache.clear()
        self.archived = PesticideNotice.objects.get(pk=1)
        self.county = self.archived.county
        self.url = self.county.get_pesticides_tab_url('notices')

    def test_lists_only_the_place(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        here = [n.county_id for n in self.client.get(kern.get_pesticides_tab_url('notices')).context['object_list']]
        assert here and set(here) == {kern.pk}

    def test_out_of_range_page_is_not_a_404(self):
        for page in ('99', 'nope'):
            assert self.client.get(self.url, {'page': page}).status_code == 200

    def test_past_mode_lists_the_archive_and_counts_only_the_place(self):
        response = self.client.get(self.url, {'past': 1})
        assert [n.pk for n in response.context['object_list']] == [1]
        assert [(m['year'], m['month'], m['count']) for m in response.context['archive_months']] == [(2020, 1, 1)]
        # The stat row is what's scheduled now, whatever the mode.
        assert response.context['upcoming_count'] == self.client.get(self.url).context['upcoming_count']

    def test_chemical_filter_and_own_chip(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(kern.get_pesticides_tab_url('notices'), {'chemical': chem.sqid})
        assert [n.pk for n in response.context['object_list']] == [3]
        labels = [f['label'] for f in response.context['active_filters']]
        assert labels == [chem.display_name]

    def test_layout(self):
        from camp.apps.pesticides.tests.test_area_layout import side
        html = self.client.get(self.url, {'past': 1}).content.decode()
        panel = side(html)
        assert 'notice-filters' in panel and 'archive-months' in panel and 'spraydays' in panel.lower()
        assert 'Day by day' not in html and 'Past notices here' not in html
        assert html.index('class="column tab-map"') < html.index('summary-sentence')

    def test_near_me_filters_keep_the_point(self):
        response = self.client.get(reverse('pesticides:near-me-notices'), self.POINT)
        assert response.status_code == 200
        html = response.content.decode()
        form = html[html.index('notice-filters'):html.index('</form>', html.index('notice-filters'))]
        for name, value in (('lat', '36.71'), ('lng', '-119.79'), ('radius', '3'), ('label', 'near Selma')):
            assert f'name="{name}"' in form and value in form, name
        clear = response.context['clear_filters_url']
        assert clear.startswith(reverse('pesticides:near-me-notices')) and 'lat=36.71' in clear and 'label=near+Selma' in clear
        assert not [f for f in response.context['active_filters'] if f['label'].startswith('Within ')]

    def test_filter_form_carries_year_and_label(self):
        html = self.client.get(self.url, {'year': 2022}).content.decode()
        form = html[html.index('notice-filters'):html.index('</form>', html.index('notice-filters'))]
        assert '<input type="hidden" name="year" value="2022">' in form

    def test_paginates(self):
        assert self.client.get(self.url).context['paginator'].per_page == 50

    def test_region_tab_drops_its_own_chip(self):
        city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY)
        poly = Polygon(((-119.9, 36.6), (-119.7, 36.6), (-119.7, 36.8), (-119.9, 36.8), (-119.9, 36.6)), srid=4326)
        city.boundary = Boundary.objects.create(region=city, version='test', geometry=MultiPolygon(poly, srid=4326))
        city.save()
        response = self.client.get(city.get_pesticides_tab_url('notices'))
        assert response.status_code == 200
        assert city.name not in [f['label'] for f in response.context['active_filters']]
