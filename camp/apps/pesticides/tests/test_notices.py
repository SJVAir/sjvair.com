import re
from html import unescape
from urllib.parse import parse_qs, urlparse

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

    def test_summary_sentence_names_the_picked_month(self):
        past = self.client.get(self.url, {'past': 1, 'month': 'all'})
        assert 'in the archive.' in past.content.decode()
        month = self.client.get(self.url, {'past': 1, 'archive_year': 2020, 'month': 1})
        assert 'in the archive in January 2020.' in ' '.join(month.content.decode().split())

    def test_archive_months_has_all_months_first(self):
        html = self.client.get(self.url, {'past': 1, 'month': 'all'}).content.decode()
        assert 'All months</a>' in html
        assert html.index('All months') < html.index('January 2020')
        all_link = html[html.rindex('<a', 0, html.index('All months')):html.index('All months')]
        assert 'is-active' in all_link
        picked = self.client.get(self.url, {'past': 1, 'archive_year': 2020, 'month': 1}).content.decode()
        all_link = picked[picked.rindex('<a', 0, picked.index('All months')):picked.index('All months')]
        assert 'is-active' not in all_link
        assert 'month=all' in all_link and 'archive_year' not in all_link

    def test_past_lands_on_the_newest_month(self):
        # Scheduled -> Past sends `past=1` alone: same as picking the newest month.
        response = self.client.get(self.url, {'past': 1})
        assert response.context['filter_year'] == 2020 and response.context['filter_month'] == 1
        assert [n.pk for n in response.context['object_list']] == [1]
        notices_url = response.context['map_config']['notices_url']
        assert 'year=2020' in notices_url and 'month=1' in notices_url
        html = response.content.decode()
        assert 'in the archive in January 2020.' in ' '.join(html.split())
        all_link = html[html.rindex('<a', 0, html.index('All months')):html.index('All months')]
        assert 'is-active' not in all_link
        jan_link = html[html.rindex('<a', 0, html.index('January 2020 <')):html.index('January 2020 <')]
        assert 'is-active' in jan_link

    def test_past_with_an_empty_archive_has_no_month(self):
        other = Region.objects.filter(type=Region.Type.COUNTY).exclude(pk=PesticideNotice.objects.get(pk=1).county_id).first()
        response = self.client.get(self.url, {'past': 1, 'county': other.slug})
        assert response.status_code == 200
        assert response.context['filter_year'] is None and response.context['filter_month'] is None
        assert list(response.context['object_list']) == []
        assert response.context['map_config']['notices_url'] == reverse('api:v2:pesticides:notice-archive')

    def test_all_months_is_an_explicit_choice(self):
        response = self.client.get(self.url, {'past': 1, 'month': 'all'})
        assert response.status_code == 200
        assert response.context['filter_year'] is None and response.context['filter_month'] is None
        assert [n.pk for n in response.context['object_list']] == [1]
        assert response.context['map_config']['notices_url'] == reverse('api:v2:pesticides:notice-archive')
        html = response.content.decode()
        all_link = html[html.rindex('<a', 0, html.index('All months')):html.index('All months')]
        assert 'is-active' in all_link
        assert '<input type="hidden" name="month" value="all">' in html
        # ...and it doesn't leak into Scheduled.
        assert 'value="all"' not in self.client.get(self.url, {'month': 'all'}).content.decode()

    def test_defaulted_month_is_not_pinned_by_the_filter_form(self):
        def form_inputs(params):
            html = self.client.get(self.url, params).content.decode()
            form = html[html.index('notice-filters'):html.index('</form>', html.index('notice-filters'))]
            return form
        defaulted = form_inputs({'past': 1})
        assert 'name="archive_year"' not in defaulted and 'name="month"' not in defaulted
        picked = form_inputs({'past': 1, 'archive_year': 2020, 'month': 1})
        assert 'name="archive_year" value="2020"' in picked and 'name="month" value="1"' in picked
        assert 'name="month" value="all"' in form_inputs({'past': 1, 'month': 'all'})

    def test_month_without_a_year_is_no_month(self):
        response = self.client.get(self.url, {'past': 1, 'month': 3})
        assert (response.context['filter_year'], response.context['filter_month']) == (2020, 1)
        assert [n.pk for n in response.context['object_list']] == [1]
        html = response.content.decode()
        assert 'name="month" value="3"' not in html
        assert 'month=3' not in response.context['map_config']['section_notices_url']

    def test_bad_month_is_ignored(self):
        for month in ('13', '0', 'x'):
            response = self.client.get(self.url, {'past': 1, 'month': month})
            assert response.status_code == 200, month
            assert response.context['filter_month'] == 1, month

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
            # A place's notices are on its Notices tab, as the list's rows;
            # the other pages carry their own `upcoming` list.
            'place': (reverse('pesticides:region-notices', kwargs={'sqid': fresno.sqid, 'slug': fresno.slug}), 'object_list'),
            'section': (reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}), 'upcoming'),
            'chemical': (Chemical.objects.get(pk=1).get_absolute_url(), 'upcoming'),
        }
        for name, (url, key) in pages.items():
            response = self.client.get(url)
            upcoming = response.context.get(key) or []
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

    def test_past_lands_on_the_newest_month(self):
        response = self.client.get(self.url, {'past': 1})
        assert (response.context['filter_year'], response.context['filter_month']) == (2020, 1)
        assert [n.pk for n in response.context['object_list']] == [1]
        assert response.context['notice_stats']['count'] == 1
        notices_url = response.context['map_config']['notices_url']
        assert 'year=2020' in notices_url and 'month=1' in notices_url
        assert response.context['map_config']['section_notices_url'].count('month=1') == 1
        assert 'in the archive in January 2020 here.' in ' '.join(self.client.get(self.url, {'past': 1}).content.decode().split())

    def test_past_mode_lists_the_archive_and_counts_only_the_place(self):
        response = self.client.get(self.url, {'past': 1})
        assert [n.pk for n in response.context['object_list']] == [1]
        assert [(m['year'], m['month'], m['count']) for m in response.context['archive_months']] == [(2020, 1, 1)]
        # The stat row counts what the list shows, whatever the mode.
        assert response.context['notice_stats']['count'] == 1
        assert self.client.get(self.url).context['notice_stats']['count'] == 1

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

    def test_near_me_archive_links_keep_the_point(self):
        url = reverse('pesticides:near-me-notices')
        # Put the archived notice in a section, and the point on that section.
        section = Region.objects.get(pk=9101)
        PesticideNotice.objects.filter(pk=1).update(mtrs_id=section.pk)
        centre = section.boundary.geometry.centroid
        point = {'lat': round(centre.y, 4), 'lng': round(centre.x, 4), 'radius': 3, 'label': 'near Selma'}
        response = self.client.get(url, {**point, 'past': 1})
        assert response.context['archive_months']
        html = response.content.decode()
        box = html[html.index('archive-months'):]
        box = box[:box.index('</ul>')]
        links = [unescape(h) for h in re.findall(r'href="([^"]*)"', box)]
        assert len(links) == len(response.context['archive_months']) + 1
        for link in links:
            query = parse_qs(urlparse(link).query)
            # Query-only links stay on the page they're on.
            assert urlparse(link).path in ('', url), link
            assert query['past'] == ['1'], link
            for name, value in point.items():
                assert query[name] == [str(value)], (link, name)
        assert parse_qs(urlparse(links[0]).query)['month'] == ['all']

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


class CountyColumnTests(RollupTestMixin, TestCase):
    """The County column is dropped where every row is the same county."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')

    def headers(self, html):
        return html[html.index('<thead>'):html.index('</thead>')]

    def test_hidden_on_one_county(self):
        for url, params in (
            (self.kern.get_pesticides_tab_url('notices'), {}),
            (self.kern.get_pesticides_tab_url('records'), {}),
            (reverse('pesticides:notice-list'), {'county': 'kern'}),
            (reverse('pesticides:records'), {'county': 'kern'}),
        ):
            response = self.client.get(url, params)
            assert response.context['county'] == self.kern, url
            assert '<th>County</th>' not in self.headers(response.content.decode()), url

    def test_shown_valley_wide_and_near_me(self):
        near_me = {'lat': 36.71, 'lng': -119.79, 'radius': 3}
        for url, params in (
            (reverse('pesticides:notice-list'), {}),
            (reverse('pesticides:records'), {}),
            (reverse('pesticides:near-me-notices'), near_me),
            (reverse('pesticides:near-me-records'), near_me),
        ):
            response = self.client.get(url, params)
            assert response.status_code == 200, url
            assert not response.context['county'], url
            assert '<th>County</th>' in self.headers(response.content.decode()), url


class NoticeModeTests(TestCase):
    """Scheduled / Past is a filter on the whole notices page."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.archived = PesticideNotice.objects.get(pk=1)
        self.tab = self.archived.county.get_pesticides_tab_url('notices')

    def form(self, html):
        start = html.index('notice-filters')
        return html[start:html.index('</form>', start)]

    def test_mode_is_a_field_in_the_filter_box(self):
        for url in (reverse('pesticides:notice-list'), self.tab):
            form = self.form(self.client.get(url).content.decode())
            assert 'name="past"' in form, url
            assert 'tabs is-toggle' not in self.client.get(url).content.decode().split('notice-filters')[0], url

    def test_mode_radios_are_keyboard_focusable(self):
        form = self.form(self.client.get(self.tab).content.decode())
        radios = re.findall(r'<input[^>]*name="past"[^>]*>', form)
        assert len(radios) == 2
        for radio in radios:
            # `hidden` takes a control out of the tab order; screen-reader-only keeps it in.
            assert ' hidden' not in radio and 'is-sr-only' in radio, radio

    def test_switching_mode_drops_month_and_page(self):
        html = self.client.get(self.tab, {'past': 1, 'archive_year': 2020, 'month': 1, 'page': 2}).content.decode()
        form = self.form(html)
        # The month and page ride along only while Past stays chosen; the
        # Scheduled choice must not submit them.
        assert 'name="page"' not in form
        scheduled = re.search(r'<input[^>]*name="past"[^>]*value=""[^>]*>|<input[^>]*value=""[^>]*name="past"[^>]*>', form)
        assert scheduled, 'no Scheduled option'

    def test_a_stale_month_is_ignored_outside_past_mode(self):
        for page in (reverse('pesticides:notice-list'), self.tab):
            context = self.client.get(page, {'archive_year': 2020, 'month': 2}).context
            assert context['filter_year'] is None and context['filter_month'] is None
            assert context['map_config']['notices_url'].startswith('/api/2.0/pesticides/notices/active/')
            assert 'name="archive_year"' not in self.form(self.client.get(page, {'archive_year': 2020, 'month': 2}).content.decode())

    def test_stats_follow_the_mode(self):
        past = self.client.get(self.tab, {'past': 1}).context
        assert past['notice_stats']['count'] == 1
        month = self.client.get(self.tab, {'past': 1, 'archive_year': 2020, 'month': 2}).context
        assert month['notice_stats']['count'] == 0

    def test_stats_follow_a_chemical_filter(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        chem = Chemical.objects.get(pk=1)
        url = kern.get_pesticides_tab_url('notices')
        assert self.client.get(url, {'chemical': chem.sqid}).context['notice_stats']['count'] == 1
        # Chemical 1 is only on Kern's notice; Fresno's one lists chemical 2.
        fresno = self.tab
        assert self.client.get(fresno, {'chemical': chem.sqid}).context['notice_stats']['count'] == 0
        other = Chemical.objects.get(pk=2)
        assert self.client.get(fresno, {'chemical': other.sqid}).context['notice_stats']['count'] == 1

    def test_map_follows_the_mode(self):
        url = reverse('api:v2:pesticides:notice-archive')
        for page in (reverse('pesticides:notice-list'), self.tab):
            assert self.client.get(page).context['map_config']['notices_url'].startswith('/api/2.0/pesticides/notices/active/')
            assert self.client.get(page, {'past': 1, 'month': 'all'}).context['map_config']['notices_url'] == url
            month = self.client.get(page, {'past': 1, 'archive_year': 2020, 'month': 1}).context['map_config']['notices_url']
            assert month.startswith(url + '?') and 'year=2020' in month and 'month=1' in month

    def test_popup_notices_link_keeps_the_mode(self):
        for page in (reverse('pesticides:notice-list'), self.tab):
            scheduled = self.client.get(page).context['map_config']['section_notices_url']
            assert 'past=1' not in scheduled
            past = self.client.get(page, {'past': 1, 'month': 'all'}).context['map_config']['section_notices_url']
            assert past.startswith(reverse('pesticides:notice-list') + '?section={id}') and 'past=1' in past
            assert 'month=all' in past and 'archive_year' not in past
            newest = self.client.get(page, {'past': 1}).context['map_config']['section_notices_url']
            assert 'archive_year=2020' in newest and 'month=1' in newest
            month = self.client.get(page, {'past': 1, 'archive_year': 2020, 'month': 1}).context['map_config']['section_notices_url']
            assert 'past=1' in month and 'archive_year=2020' in month and 'month=1' in month

    def test_options_label_follows_the_mode(self):
        for page in (reverse('pesticides:notice-list'), self.tab):
            assert 'Notices of intent</label>' in self.client.get(page).content.decode()
            assert 'Past notices</label>' not in self.client.get(page).content.decode()
            past = self.client.get(page, {'past': 1}).content.decode()
            assert 'Past notices</label>' in past and 'Notices of intent</label>' not in past

    def test_tab_skips_the_upcoming_context(self):
        context = self.client.get(self.tab).context
        for key in ('upcoming_days', 'upcoming', 'upcoming_by_county'):
            assert key not in context, key
