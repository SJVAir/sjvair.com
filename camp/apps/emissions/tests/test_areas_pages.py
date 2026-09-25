import json
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import views
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.regions.models import Region


def map_data(content, key):
    match = re.search(rf'class="facility-map map-canvas"[^>]*data-{key}="([^"]*)"', content)
    return match.group(1) if match else None


class RegionPageTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def get(self, region, params=None, status=200):
        response = self.client.get(region.get_emissions_url(), params or {})
        assert response.status_code == status, response.status_code
        return response.content.decode()

    def test_county_page(self):
        content = self.get(self.fresno, {'year': '2024'})
        assert '<h1' in content and 'Fresno County' in content
        assert 'TEST PLANT' in content
        # The page is the area: no county picker in the scope bar.
        assert 'data-scope="county"' not in content
        assert map_data(content, 'areas') == '1'
        assert map_data(content, 'level') == 'zipcode'
        assert map_data(content, 'outline-url') == reverse('api:v2:regions:region-detail', args=[self.fresno.sqid])

    def test_city_page_counts_by_point(self):
        city = Region.objects.get(type=Region.Type.CITY, slug='fresno')
        content = self.get(city, {'year': '2024'})
        assert 'TEST PLANT' in content
        assert map_data(content, 'level') == 'tract'

    def test_tract_page(self):
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT, population=4321)
        tract.metadata = {**tract.metadata, 'namelsad': 'Census Tract 1'}
        tract.save(update_fields=['metadata'])
        content = self.get(tract, {'year': '2024'})
        assert 'Census Tract 1' in content and '4,321' in content
        assert 'TEST PLANT' in content
        assert map_data(content, 'areas') == ''  # the finest level: Facilities only

    def test_retired_tracts_and_other_types_404(self):
        old = make(Region.Type.TRACT, 'Old', AROUND_PLANT, version='2010')
        self.get(old, status=404)
        district = Region.objects.create(name='SJV APCD', slug='sjv-apcd', type=Region.Type.AIR_DISTRICT)
        response = self.client.get(reverse('emissions:region', args=[district.sqid, district.slug]))
        assert response.status_code == 404

    def test_redirects(self):
        wrong = reverse('emissions:region', args=[self.fresno.sqid, 'wrong']) + '?year=2024'
        response = self.client.get(wrong)
        assert response.status_code == 301 and response['Location'] == self.fresno.get_emissions_url() + '?year=2024'
        response = self.client.get(reverse('emissions:region-redirect', args=[self.fresno.sqid]))
        assert response.status_code == 301 and response['Location'] == self.fresno.get_emissions_url()

    def test_view_level_and_measure_from_the_url(self):
        content = self.get(self.fresno, {'view': 'areas', 'level': 'tract', 'measure': 'total'})
        assert (map_data(content, 'view'), map_data(content, 'level'), map_data(content, 'measure')) == ('areas', 'tract', 'total')
        content = self.get(self.fresno, {'view': 'bogus', 'level': 'mtrs', 'measure': 'x'})
        assert (map_data(content, 'view'), map_data(content, 'level'), map_data(content, 'measure')) == ('facilities', 'zipcode', 'density')


class NearMeTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.url = reverse('emissions:near-me')

    def test_page(self):
        response = self.client.get(self.url, {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Fresno', 'year': '2024'})
        assert response.status_code == 200
        content = response.content.decode()
        assert 'near Fresno' in content and 'TEST PLANT' in content
        assert map_data(content, 'radius') == '1'
        assert map_data(content, 'center') == '36.7370,-119.7870'

    def test_bad_input_bounces_to_the_find_form(self):
        home = reverse('emissions:home') + '?find=1'
        for params in ({}, {'lat': 'x', 'lng': '1'}, {'lat': '36.7', 'lng': '-119.7', 'radius': '2'},
                       {'lat': '91', 'lng': '0'}, {'lat': 'nan', 'lng': '-119.7'},
                       {'lat': '47.6', 'lng': '-122.3'}):  # Seattle: outside every covered county
            response = self.client.get(self.url, params)
            assert response.status_code == 302 and response['Location'] == home, params

    def test_long_label_is_cut(self):
        response = self.client.get(self.url, {'lat': '36.737', 'lng': '-119.787', 'label': 'x' * 500})
        assert 'x' * 121 not in response.content.decode()


class FindAreaTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_home_has_the_search_box_without_tracts(self):
        cache.clear()
        make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        content = self.client.get(reverse('emissions:home')).content.decode()
        assert f'data-near-url="{reverse("emissions:near-me")}"' in content
        places = json.loads(re.search(r'id="find-area-places"[^>]*>(.*?)</script>', content, re.S).group(1))
        assert {place['type'] for place in places} <= {'county', 'city', 'zipcode', 'place', 'school_district'}
        fresno = next(place for place in places if place['name'] == 'Fresno County')
        assert fresno['url'] == Region.objects.get(type='county', slug='fresno').get_emissions_url()
