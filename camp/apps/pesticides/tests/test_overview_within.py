from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Region


class OverviewWithinTests(TestCase):
    """The old Community tab is gone: In and around sits at the foot of a place's Overview."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)
        self.overview = self.fresno.get_pesticides_tab_url('overview')

    def test_no_community_tab(self):
        response = self.client.get(self.overview)
        assert 'community' not in [tab['key'] for tab in response.context['tabs']]

    def test_the_old_tab_redirects_to_overview(self):
        url = reverse('pesticides:region-community', kwargs={'sqid': self.fresno.sqid, 'slug': self.fresno.slug})
        response = self.client.get(url, {'year': 2023})
        assert response.status_code == 301
        assert response['Location'] == f'{self.overview}?year=2023#in-and-around'
        response = self.client.get(reverse('pesticides:near-me-community'), {'lat': 36.71, 'lng': -119.79})
        assert response.status_code == 301
        assert response['Location'] == f'{reverse("pesticides:near-me")}?lat=36.71&lng=-119.79#in-and-around'


class HeaderLinksTests(RollupTestMixin, TestCase):
    """A place page's header: the same town on the other community layer, and the same place in emissions."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)
        geometry = MultiPolygon(Polygon.from_bbox((-119.8, 36.7, -119.7, 36.8)), srid=4326)
        self.city = self.make('Selma', Region.Type.CITY, geometry)
        self.urban = self.make('Selma', Region.Type.URBAN_AREA, geometry)

    def make(self, name, kind, geometry):
        region = Region.objects.create(name=name, slug=f'selma-{kind}', type=kind, external_id=f'x-{kind}')
        region.boundary = Boundary.objects.create(region=region, version='t', geometry=geometry)
        region.save()
        return region

    def test_a_city_links_its_urban_area_and_back(self):
        for region, other, label in ((self.city, self.urban, 'Switch to urban area'), (self.urban, self.city, 'Switch to city limits')):
            for tab in ('overview', 'notices'):
                response = self.client.get(region.get_pesticides_tab_url(tab), {'year': 2022})
                assert response.status_code == 200
                link = {'label': label, 'url': f'{other.get_pesticides_tab_url(tab)}?year=2022', 'internal': True}
                assert link in response.context['header_links'], (region.type, tab)
                html = response.content.decode()
                assert f'<a class="button is-small is-rounded area-switch" href="{other.get_pesticides_tab_url(tab)}?year=2022">' in html
                assert f'<span>{label}</span></a>' in html

    def test_a_county_has_no_counterpart(self):
        response = self.client.get(self.fresno.get_pesticides_tab_url('overview'))
        assert not [link for link in response.context['header_links'] if link.get('internal')]

    def test_region_tabs_link_to_emissions(self):
        response = self.client.get(self.fresno.get_pesticides_tab_url('records'))
        assert [link['label'] for link in response.context['tab_links']] == ['Emissions']
        assert response.context['tab_links'][0]['url'] == self.fresno.get_emissions_url()
        response = self.client.get(self.fresno.get_pesticides_tab_url('schools'))
        assert response.context['tab_links'][0]['url'] == self.fresno.get_emissions_tab_url('schools')

    def test_near_me_links_to_emissions_at_the_same_point(self):
        response = self.client.get(reverse('pesticides:near-me-schools'), {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma', 'year': 2023})
        url = response.context['tab_links'][0]['url']
        assert url == f'{reverse("emissions:near-me-schools")}?lat=36.71&lng=-119.79&radius=3&label=near+Selma'

    def test_a_county_header_leaves_out_its_type(self):
        response = self.client.get(self.fresno.get_pesticides_tab_url('overview'))
        assert response.context['kind'] == ''
        response = self.client.get(self.city.get_pesticides_tab_url('overview'))
        # The emissions header's line: type, county, population (none here).
        assert response.context['kind'] == 'City · Fresno County'
        assert [crumb['label'] for crumb in response.context['area_crumbs']] == ['Fresno County', response.context['area'].page_title]
        assert f'<li><a href="{self.fresno.get_pesticides_url()}">Fresno County</a></li>' in response.content.decode()
