import csv
import io
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import dairies, dairy_views
from camp.apps.emissions.models import DairyHerd
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_dairies import dairy_inventory, make_dairies
from camp.apps.regions.models import Region


def dairy_map_data(content, key):
    match = re.search(rf'class="dairy-map map-canvas"[^>]*data-{key}="([^"]*)"', content)
    return match.group(1) if match else None


class DairyPageTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.big, self.small, self.closed = make_dairies()
        self.url = reverse('emissions:dairy-list')

    def get(self, params=None):
        response = self.client.get(self.url, params or {})
        assert response.status_code == 200, response.status_code
        return response


class DairyTabScopeTests(DairyPageTestCase):
    def test_a_bare_url_falls_back_quietly(self):
        response = self.get()
        content = response.content.decode()
        scope = response.context['scope']
        assert (scope.year, scope.pollutant.key) == (2023, 'rog')
        assert 'dairy-note' not in content
        # The fallbacks are the page's scope, so its links carry them onward.
        assert 'href="?year=2022&amp;pollutant=rog"' in content
        assert f'href="{reverse("emissions:facility-list")}?year=2023&amp;pollutant=rog"' in content

    def test_nox_falls_back_to_rog_with_a_note(self):
        response = self.get({'pollutant': 'nox'})
        assert response.context['scope'].pollutant.key == 'rog'
        assert 'Dairies report no NOx; showing ROG.' in response.content.decode()

    def test_toxics_fall_back_with_a_note(self):
        content = self.get({'toxics': '1', 'pollutant': 'benzene'}).content.decode()
        assert 'Dairies report no toxic air contaminants; showing ROG.' in content
        assert 'toxics=1' not in content

    def test_a_year_outside_cadd_falls_back_with_a_note(self):
        response = self.get({'year': '2024'})
        assert response.context['scope'].year == 2023
        assert 'CADD has herd data for 2022–2023; showing 2023.' in response.content.decode()

    def test_options_that_dont_apply_are_disabled_with_tooltips(self):
        content = self.get().content.decode()
        for label in ('NOx', 'SOx', 'CO'):
            assert f'data-tooltip="CARB reports no {label} from dairy cattle"' in content
        assert 'pollutant=nox' not in content
        assert 'data-tooltip="CADD has herd data for 2022–2023"' in content
        assert 'href="?year=2024' not in content
        assert 'data-tooltip="CARB reports no toxic air contaminants for dairy cattle"' in content
        assert 'toxics=1' not in content and 'minor=1' not in content
        # ROG, Total PM, PM10 and TOG stay links.
        assert 'href="?year=2023&amp;pollutant=pm10"' in content

    def test_other_pages_are_unchanged(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert 'aria-disabled' not in content
        assert 'pollutant=nox' in content and 'toxics=1' in content


class DairyTabContentTests(DairyPageTestCase):
    def test_headline_numbers(self):
        content = self.get().content.decode()
        assert '<p class="heading">Dairies in 2023</p><p class="title">2</p>' in content
        assert '<p class="heading">Animal units (EPA)</p><p class="title">2,310</p>' in content
        assert '<p class="heading">Milk cows</p><p class="title">1,200</p>' in content
        assert '<p class="heading">With a digester</p><p class="title">1</p>' in content

    def test_the_county_narrows_the_numbers_the_table_and_the_map(self):
        content = self.get({'county': 'kern'}).content.decode()
        assert 'SMALL DAIRY' in content and 'BIG DAIRY' not in content
        assert '<p class="heading">Dairies in 2023</p><p class="title">1</p>' in content
        assert dairy_map_data(content, 'county') == 'kern'

    def test_table(self):
        content = self.get().content.decode()
        assert content.index('BIG DAIRY') < content.index('SMALL DAIRY')
        assert 'CLOSED DAIRY' not in content
        assert f'class="dairy-zoom" data-dairy="{self.big.sqid}" data-lng="-119.78500" data-lat="36.73500"' in content
        assert 'Yes, since 2019' in content
        assert f'href="{self.fresno.get_emissions_url()}?year=2023&amp;pollutant=rog"' in content
        content = self.get({'sort': 'name'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('SMALL DAIRY')
        assert 'sort=-animal_units' in content
        content = self.get({'q': 'small'}).content.decode()
        assert 'SMALL DAIRY' in content and 'BIG DAIRY' not in content

    def test_region_filter(self):
        place = make(Region.Type.PLACE, 'Plantville', AROUND_PLANT)
        content = self.get({'region': place.sqid}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content
        assert 'Plantville <button' in content

    def test_a_tract_from_its_region_page(self):
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        content = self.get({'region': tract.sqid}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content

    def test_near_me_filter_and_its_tag(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Tower District'}
        content = self.get(params).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content
        assert 'Within 1 mi of Tower District' in content
        assert '<input type="hidden" name="lat" value="36.737">' in content
        remove = re.search(r'href="([^"]*)" aria-label="Remove the distance filter"', content).group(1)
        assert 'lat=' not in remove and 'label=' not in remove
        # A radius near-me doesn't offer is no filter at all.
        content = self.get({**params, 'radius': '2'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' in content

    def test_csv(self):
        response = self.client.get(self.url, {'format': 'csv', 'county': 'fresno'})
        assert response['Content-Type'] == 'text/csv'
        assert 'dairies-2023.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['dairy'] for row in rows] == ['BIG DAIRY']
        big = rows[0]
        assert (big['cadd_id'], big['county'], big['animal_units'], big['milk_cows'], big['beef_cattle']) == ('1', 'Fresno County', '2120.0', '1100', '')
        assert (big['digester_operating'], big['digester_since']) == ('yes', '2019')

    def test_map(self):
        content = self.get().content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('dairies', 'emissions')
        assert dairy_map_data(content, 'geojson-url') == '/api/2.0/emissions/dairies/geojson/?year=2023'
        assert 'data-view="counties"' in content and 'data-measure="animal_units_per_sq_mi"' in content
        content = self.get({'view': 'counties', 'measure': 'animal_units'}).content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('counties', 'animal_units')
        content = self.get({'view': 'bogus', 'measure': 'x'}).content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('dairies', 'emissions')

    def test_map_config(self):
        scope, _ = dairies.resolve_scope({'county': 'kern', 'pollutant': 'pm10'})
        config = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({}))
        assert config['counties_url'].endswith('/dairies/counties/?year=2023&pollutant=pm10')
        assert config['popup_url'].endswith('/dairies/{id}/?year=2023')
        assert (config['county'], config['label']) == ('kern', 'PM10')
        assert config['map']['data']['source-note'] == 'CARB county inventory, dairy cattle waste; silage not included'
        assert config['map']['container_id'] == 'dairy-map'

    def test_coverage_note_before_2019(self):
        DairyHerd.objects.create(dairy=self.big, year=2018, milk_cows=900, animal_units=1260)
        dairies.clear_caches()
        assert 'CADD tracked fewer dairies before 2019' in self.get({'year': '2018'}).content.decode()
        assert 'CADD tracked fewer dairies before 2019' not in self.get().content.decode()

    def test_trend_chart(self):
        content = self.get().content.decode()
        assert 'Animal units (solid) and milk cows (dashed) by year' in content
        assert '"y2": [1000, 1200]' in content

    def test_no_data_yet(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        content = self.get().content.decode()
        assert 'No dairy data has been loaded yet.' in content
        assert 'class="dairy-map map-canvas"' not in content

    def test_tab(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert f'href="{self.url}' in content and 'fa-cow' in content
