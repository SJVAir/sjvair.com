from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Location, Region


class MapFollowsTableFiltersTests(RollupTestMixin, TestCase):
    """A list page's map is narrowed the way its table is, or says where it isn't."""
    fixtures = ['pesticides-explorer']

    def test_records_method_reaches_the_grid_endpoints(self):
        config = self.client.get(reverse('pesticides:records'), {'year': 2023, 'method': 'A'}).context['map_config']
        assert config['sections_url'].endswith('?method=A')
        assert config['townships_url'].endswith('?method=A')
        unfiltered = self.client.get(reverse('pesticides:records'), {'year': 2023}).context['map_config']
        assert '?' not in unfiltered['sections_url']

    def test_records_notes_the_filters_the_map_cannot_follow(self):
        response = self.client.get(reverse('pesticides:records'), {'year': 2023})
        assert response.context['map_unfiltered'] == []
        assert 'map-unfiltered' not in response.content.decode()
        response = self.client.get(reverse('pesticides:records'), {'year': 2023, 'start': '2023-03-15'})
        assert response.context['map_unfiltered'] == ['dates']
        assert "The map isn't narrowed by dates; the table is." in response.content.decode()

    def test_notice_method_reaches_the_notices_endpoint(self):
        config = self.client.get(reverse('pesticides:notice-list'), {'method': 'Ground'}).context['map_config']
        assert config['notices_url'] == '/api/2.0/pesticides/notices/active/?method=Ground'
        assert config['notices_past'] == '0'

    def test_place_notices_tab_method_reaches_the_notices_endpoint(self):
        fresno = Region.objects.get(pk=9001)
        config = self.client.get(fresno.get_pesticides_tab_url('notices'), {'method': 'Ground'}).context['map_config']
        assert config['notices_url'].endswith('method=Ground')

    def test_schools_filters_narrow_the_map_to_the_listed_sites(self):
        fresno = Region.objects.get(pk=9001)
        inside = fresno.boundary.geometry.point_on_surface
        school = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL, name='Inside High', external_id='x-school', source='cde-public', point=inside)
        Location.objects.create(
            type=Location.Type.CHILD_CARE, name='Inside Child Care', external_id='x-care', source='cdss-ccl', point=inside)
        url = fresno.get_pesticides_tab_url('schools')
        config = self.client.get(url).context['map_config']
        assert config['locations_filtered'] == '0' and config['location_ids'] == ''
        config = self.client.get(url, {'schools_type': Location.Type.PUBLIC_SCHOOL}).context['map_config']
        assert config['locations_filtered'] == '1' and config['location_ids'] == school.sqid
        config = self.client.get(url, {'schools_q': 'no such school'}).context['map_config']
        assert config['locations_filtered'] == '1' and config['location_ids'] == ''


class ScopedMapsDrawEverySectionTests(RollupTestMixin, TestCase):
    """Townships are for the valley-wide view; a county or place draws its sections."""
    fixtures = ['pesticides-explorer']

    def config(self, url, params):
        response = self.client.get(url, params)
        return response.context['map_config'], response.content.decode()

    def test_a_county_scope_draws_every_section_without_the_toggle(self):
        for url in (reverse('pesticides:records'), reverse('pesticides:map'), reverse('pesticides:notice-list')):
            config, html = self.config(url, {'year': 2023, 'county': 'fresno'})
            assert config['sections_fixed'] == '1' and config['show_all_sections'] == '1', url
            assert 'name="sections"' not in html, url

    def test_the_valley_keeps_townships_and_the_toggle(self):
        for url in (reverse('pesticides:records'), reverse('pesticides:map')):
            config, html = self.config(url, {'year': 2023})
            assert config['sections_fixed'] == '0' and config['show_all_sections'] == '0', url
            assert 'name="sections"' in html, url

    def test_records_narrowed_to_a_region_draw_every_section(self):
        fresno = Region.objects.get(pk=9001)
        config, _ = self.config(reverse('pesticides:records'), {'year': 2023, 'region': fresno.sqid})
        assert config['sections_fixed'] == '1'


class MapFramesItsFocusTests(RollupTestMixin, TestCase):
    """A section, place or point the page is about frames the map; a county filter alone frames the county."""
    fixtures = ['pesticides-explorer']

    def config(self, name, **params):
        return self.client.get(reverse(name), params).context['map_config']

    def test_a_section_with_a_county_keeps_the_section(self):
        section = Region.objects.get(pk=9101)
        for name in ('pesticides:notice-list', 'pesticides:records'):
            config = self.config(name, section=section.sqid, county='fresno', year=2023)
            assert config['framed'] == '1', name
            assert config['zoom'] == 13, name

    def test_a_county_alone_frames_the_county(self):
        for name in ('pesticides:notice-list', 'pesticides:records'):
            assert self.config(name, county='fresno', year=2023)['framed'] == '0', name

    def test_a_point_frames_itself(self):
        config = self.config('pesticides:notice-list', lat=36.71, lng=-119.79, radius=3, county='fresno')
        assert config['framed'] == '1'


class ValleyMapLayersTests(RollupTestMixin, TestCase):
    """The valley map starts with every marker layer on; a list page keeps schools off."""
    fixtures = ['pesticides-explorer']

    def test_valley_map_shows_schools_and_notices(self):
        config = self.client.get(reverse('pesticides:map'), {'year': 2023}).context['map_config']
        assert config['show_locations'] == '1' and config['show_notices'] == '1'
        assert config['show_all_sections'] == '0'

    def test_records_map_keeps_schools_off(self):
        config = self.client.get(reverse('pesticides:records'), {'year': 2023}).context['map_config']
        assert config['show_locations'] == '0'


class FilterBoxOrderTests(RollupTestMixin, TestCase):
    """Every map tab's filter box: the search (where there is one), Search by location, then the filters."""
    fixtures = ['pesticides-explorer']

    def html(self, url, **params):
        return self.client.get(url, params).content.decode()

    def test_records_and_notices_lead_with_location_search(self):
        fresno = Region.objects.get(pk=9001)
        for url, form_id, tab in (
            (reverse('pesticides:records'), 'records-filter-form', 'records'),
            (fresno.get_pesticides_tab_url('records'), 'records-filter-form', 'records'),
            (reverse('pesticides:notice-list'), 'notice-filter-form', 'notices'),
            (fresno.get_pesticides_tab_url('notices'), 'notice-filter-form', 'notices'),
        ):
            html = self.html(url, year=2023)
            assert html.index('find-area-query') < html.index(f'id="{form_id}"'), url
            assert f'data-near-url="{reverse(f"pesticides:near-me-{tab}")}"' in html, url
            assert f'"url": "{fresno.get_pesticides_tab_url(tab)}"' in html, url

    def test_schools_search_then_location_then_filters(self):
        fresno = Region.objects.get(pk=9001)
        html = self.html(fresno.get_pesticides_tab_url('schools'))
        assert html.index('id="id_schools_q"') < html.index('find-area-query') < html.index('id="schools-filter-form"')
        # The search sits outside the form but still submits with it.
        assert 'form="schools-filter-form"' in html and 'hx-include="#schools-filter-form"' in html

    def test_valley_map_filters_beside_it_and_its_toolbar_only_draws(self):
        html = self.html(reverse('pesticides:map'), year=2023)
        box = html[html.index('class="explorer-filters map-filters box"'):html.index('id="map-filter-form"')]
        assert 'find-area-query' in box
        form = html[html.index('id="map-filter-form"'):html.index('</form>', html.index('id="map-filter-form"'))]
        for kind in ('product', 'chemical', 'commodity'):
            assert f'data-kind="{kind}"' in form or f'name="{kind}"' in form, kind
        # Products before chemicals.
        assert form.index('Product') < form.index('Chemical')
        toolbar = html[html.index('class="map-toolbar-filters"'):html.index('map-canvas')]
        assert 'name="product"' not in toolbar and 'name="chemical"' not in toolbar and 'name="commodity"' not in toolbar
        assert f'data-near-url="{reverse("pesticides:near-me")}"' in html
