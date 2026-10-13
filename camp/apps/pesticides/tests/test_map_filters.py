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
