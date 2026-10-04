from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Region

TABS = ('overview', 'notices', 'records', 'schools')
OPTION_LABELS = ['Exact boundary', '+1 mile', '+3 miles', '+5 miles']


class RegionTabBufferTests(RollupTestMixin, TestCase):
    """A region's area tabs clip their map to the region widened by ?buffer=."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.county = Region.objects.get(pk=9001)
        self.city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY, external_id='c-selma')
        self.city.boundary = Boundary.objects.create(
            region=self.city, version='t',
            geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))',
        )
        self.city.save()

    def get(self, region, tab, **params):
        return self.client.get(region.get_pesticides_tab_url(tab), params)

    def test_every_region_tab_clips_its_map_to_the_buffer(self):
        for region in (self.city, self.county):
            for tab in TABS:
                response = self.get(region, tab, buffer=3)
                assert response.status_code == 200, (region.slug, tab)
                config = response.context['map_config']
                assert config['clip_region'] == region.sqid, (region.slug, tab)
                assert config['buffer'] == 3, (region.slug, tab)
                assert config['clip_url'] == f'/api/2.0/regions/{region.sqid}/?buffer=3', (region.slug, tab)
                assert f'data-clip-region="{region.sqid}"' in response.content.decode()

    def test_a_clipped_map_drops_the_county_filter_but_the_stats_keep_it(self):
        for tab in TABS:
            response = self.get(self.county, tab, buffer=3)
            config = response.context['map_config']
            assert config['clip_region'] == self.county.sqid and config['county'] == '', tab
            assert 'data-county=""' in response.content.decode(), tab
        assert self.get(self.county, 'overview', buffer=3).context['totals']['lbs'] == 670.0

    def test_the_records_tab_map_drops_the_county_and_keeps_the_narrowing(self):
        response = self.get(self.county, 'records', buffer=3)
        assert response.context['map_config']['county'] == ''
        assert response.context['map_config']['clip_region'] == self.county.sqid
        assert response.context['totals']['lbs'] == 670.0

    def test_the_toolbar_offers_the_four_buffers(self):
        for tab in TABS:
            response = self.get(self.city, tab, buffer=3)
            options = response.context['buffer_options']
            assert [o['label'] for o in options] == OPTION_LABELS, tab
            assert [o['label'] for o in options if o['current']] == ['+3 miles'], tab
            html = response.content.decode()
            assert 'map-buffer' in html and '+5 miles' in html, tab

    def test_tab_links_and_the_crumb_carry_the_buffer(self):
        response = self.get(self.city, 'notices', buffer=3)
        assert all('buffer=3' in tab['url'] for tab in response.context['tabs'])
        assert 'buffer=3' in response.context['area_crumbs'][0]['url']

    def test_filter_forms_carry_the_buffer(self):
        html = self.get(self.city, 'records', buffer=3).content.decode()
        assert '<input type="hidden" name="buffer" value="3">' in html
        assert 'name="buffer"' not in self.get(self.city, 'records').content.decode()

    def test_no_buffer_is_the_exact_boundary(self):
        for tab in TABS:
            response = self.get(self.city, tab)
            config = response.context['map_config']
            assert config['buffer'] == 0, tab
            assert config['clip_region'] == self.city.sqid, tab
            assert all('buffer' not in t['url'] for t in response.context['tabs']), tab
            assert [o['label'] for o in response.context['buffer_options'] if o['current']] == ['Exact boundary'], tab

    def test_a_bad_buffer_falls_back_to_zero(self):
        response = self.get(self.city, 'overview', buffer=7)
        assert response.context['map_config']['buffer'] == 0
        assert all('buffer' not in t['url'] for t in response.context['tabs'])

    def test_overview_map_config_differs_per_buffer(self):
        assert self.get(self.city, 'overview', buffer=1).context['map_config']['clip_url'] != \
            self.get(self.city, 'overview', buffer=5).context['map_config']['clip_url']
        # And again from cache.
        assert self.get(self.city, 'overview', buffer=1).context['map_config']['buffer'] == 1

    def test_near_me_tabs_are_never_clipped(self):
        point = {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'buffer': 3}
        for name in ('near-me', 'near-me-notices', 'near-me-records', 'near-me-schools'):
            response = self.client.get(reverse(f'pesticides:{name}'), point)
            config = response.context['map_config']
            assert not config['clip_region'] and not config['clip_url'], name
            assert 'buffer_options' not in response.context, name
            assert all('buffer' not in tab['url'] for tab in response.context['tabs']), name
            assert 'map-buffer' not in response.content.decode(), name

    def test_the_main_map_and_section_pages_are_not_clipped(self):
        config = self.client.get(reverse('pesticides:map'), {'buffer': 3}).context['map_config']
        assert not config['clip_region']
