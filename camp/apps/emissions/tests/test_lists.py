import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_stats import scope
from camp.apps.regions.models import Region


class ListTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')

    def names(self, **kwargs):
        return [record.facility.name for record in stats.facility_table(scope(), **kwargs)]


class FacilitySortTests(ListTestCase):
    def test_rank_puts_number_one_first_and_the_unranked_last(self):
        # TEST CEMENT is #1 for NOx; a facility that reported none has no rank.
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(nox=0)
        assert self.names(sort='rank') == ['TEST CEMENT', 'TEST PLANT']
        assert self.names(sort='-rank') == ['TEST CEMENT', 'TEST PLANT']
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(nox=1)
        assert self.names(sort='rank') == ['TEST CEMENT', 'TEST PLANT']
        assert self.names(sort='-rank') == ['TEST PLANT', 'TEST CEMENT']

    def test_city_sorts_on_the_city_shown(self):
        # TEST PLANT's city is Fresno; TEST CEMENT has none, so its address says
        # MOJAVE, and unmatched cities come last either way.
        assert self.names(sort='city') == ['TEST PLANT', 'TEST CEMENT']
        assert self.names(sort='-city') == ['TEST PLANT', 'TEST CEMENT']
        Facility.objects.filter(pk=self.cement.pk).update(city=self.plant.city)
        Facility.objects.filter(pk=self.plant.pk).update(city=None)
        assert self.names(sort='city') == ['TEST CEMENT', 'TEST PLANT']

    def test_rank_header_sorts_number_one_first(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert 'href="?sort=rank"' in content
        assert 'href="?sort=city"' in content


class RegionFilterTests(ListTestCase):
    def test_filters_to_the_facilities_whose_point_is_in_the_region(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        assert self.names(area=areas.RegionArea(cdp)) == ['TEST PLANT']

        content = self.client.get(reverse('emissions:facility-list'), {'region': cdp.sqid}).content.decode()
        assert 'TEST PLANT' in content
        assert 'TEST CEMENT' not in content
        # The picker shows the chosen region, ready to clear.
        assert 'Plantville <button' in content

    def test_ignores_regions_it_does_not_search(self):
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        content = self.client.get(reverse('emissions:facility-list'), {'region': tract.sqid}).content.decode()
        assert 'TEST CEMENT' in content

    def test_csv_follows_the_region(self):
        urban = make(Region.Type.URBAN_AREA, 'Plantville', AROUND_PLANT)
        response = self.client.get(reverse('emissions:facility-list'), {'region': urban.sqid, 'format': 'csv'})
        body = response.content.decode()
        assert 'TEST PLANT' in body
        assert 'TEST CEMENT' not in body


class FacilityTableLinkTests(ListTestCase):
    def test_city_and_county_link_to_their_region_pages(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        content = self.client.get(reverse('emissions:facility-list'), {'county': 'fresno'}).content.decode()
        # Region pages are the area; the list's ?county= doesn't ride along.
        assert f'href="{fresno.get_emissions_url()}"' in content
        assert f'href="{self.plant.city.get_emissions_url()}"' in content


class PlaceSearchTests(ListTestCase):
    def search(self, q):
        response = self.client.get(reverse('api:v2:emissions:places'), {'q': q, 'type': 'region', 'year': 2024})
        assert response.status_code == 200
        return response.json()['results']

    def test_cities_urban_areas_cdps_and_zips_prefix_first(self):
        zipcode = make(Region.Type.ZIPCODE, '93999', AROUND_PLANT)
        make(Region.Type.CDP, 'West Plantville', AROUND_PLANT)
        make(Region.Type.URBAN_AREA, 'Plantville', AROUND_PLANT)
        make(Region.Type.TRACT, 'Plantville Tract', AROUND_PLANT)
        assert [(r['name'], r['detail']) for r in self.search('plantv')] == [
            ('Plantville', 'Urban area'), ('West Plantville', 'Community'),
        ]
        assert self.search('9399') == [{'id': zipcode.sqid, 'name': '93999', 'detail': 'ZIP'}]

    def test_every_layer_of_a_name_is_offered(self):
        # A city and the urban area of the same name are both offered, labelled.
        city = self.plant.city
        make(Region.Type.URBAN_AREA, city.name, AROUND_PLANT)
        assert [r['detail'] for r in self.search(city.name) if r['name'] == city.name] == ['City', 'Urban area']

    def test_a_county_limits_it_to_places_in_that_county(self):
        inside = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        # A CDP well outside Fresno County (out by the Mojave cement plant).
        make(Region.Type.CDP, 'Plantdale', 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))')
        assert {r['name'] for r in self.search('plant')} == {'Plantville', 'Plantdale'}
        response = self.client.get(reverse('api:v2:emissions:places'), {'q': 'plant', 'county': 'fresno'})
        assert response.json()['results'] == [{'id': inside.sqid, 'name': 'Plantville', 'detail': 'Community'}]
        response = self.client.get(reverse('api:v2:emissions:places'), {'q': 'plant', 'county': 'nowhere'})
        assert response.json()['results'] == []

    def test_short_queries_find_nothing(self):
        assert self.search('p') == []


class SectorSortTests(ListTestCase):
    def rows(self, sort):
        return [row['label'] for row in stats.sort_sectors(stats.sector_breakdown(scope()), sort)]

    def test_sorts(self):
        by_value = self.rows('-value')
        assert self.rows('value') == by_value[::-1]
        assert self.rows('-share') == by_value
        assert self.rows('name') == sorted(by_value)
        assert self.rows('bogus') == by_value

    def test_headers(self):
        content = self.client.get(reverse('emissions:sector-list'), {'sort': 'name'}).content.decode()
        assert 'href="?sort=-name"' in content
        assert 'href="?sort=-facilities"' in content
        assert 'href="?sort=-share"' in content


class FacilityListLayoutTests(ListTestCase):
    def test_filters_sit_in_the_sidebar_with_sectors_a_to_z(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        form = content[content.index('class="explorer-filters box"'):content.index('</form>')]
        assert 'id="facility-q"' in form and 'id="facility-sector"' in form and 'data-kind="region"' in form
        labels = re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', form)
        names = [label for value, label in labels]
        assert names[-1] == 'Other'
        assert names[:-1] == sorted(names[:-1])
