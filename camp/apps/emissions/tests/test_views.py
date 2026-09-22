import csv
import io

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.apps.emissions import cepam
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility
from camp.apps.regions.models import Region


class ViewTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')

    def get(self, name, *args, params=None, status=200):
        response = self.client.get(reverse(f'emissions:{name}', args=args), params or {})
        assert response.status_code == status, (name, params, response.status_code)
        return response


class HomeTests(ViewTestCase):
    def test_renders_for_every_scope(self):
        for params in ({}, {'year': 2023}, {'county': 'fresno'}, {'county': 'kern', 'toxics': 1},
                       {'minor': 1}, {'pollutant': 'pm'}, {'year': 1900, 'pollutant': 'bogus'}):
            self.get('home', params=params)

    def test_top_facilities_and_totals(self):
        response = self.get('home')
        content = response.content.decode()
        assert 'TEST CEMENT' in content
        assert 'TEST GAS STATION' not in content
        assert '106' in content

    def test_context_bar_when_carb_estimates_exist(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        CountyInventory.objects.create(county=fresno, year=2024, inventory=cepam.INVENTORY,
                                       source_type='mobile', eic='723', nox=1.0)
        response = self.get('home', params={'county': 'fresno'})
        assert 'CARB estimates all sources' in response.content.decode()

    def test_no_context_bar_without_estimates(self):
        assert 'CARB estimates all sources' not in self.get('home').content.decode()


class FacilityListTests(ViewTestCase):
    def test_filters_and_sort(self):
        assert 'TEST PLANT' in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST CEMENT' not in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST PLANT' not in self.get('facility-list', params={'sector': 'cement-minerals'}).content.decode()
        self.get('facility-list', params={'sort': 'name', 'district': 'KER', 'city': 'fresno', 'page': 99})

    def test_minor_sources_only_when_asked(self):
        assert 'TEST GAS STATION' not in self.get('facility-list').content.decode()
        assert 'TEST GAS STATION' in self.get('facility-list', params={'minor': 1, 'pollutant': 'rog'}).content.decode()

    def test_csv(self):
        response = self.get('facility-list', params={'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        assert 'facility-emissions-2024.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['facility'] for row in rows] == ['TEST CEMENT', 'TEST PLANT']
        assert rows[0]['rank'] == '1'
        assert rows[0]['air_district'] == 'Eastern Kern APCD'
        assert float(rows[0]['nox_tons']) == 100.0
        assert float(rows[1]['benzene_lbs']) == 2.0

    def test_queries_do_not_grow_with_rows(self):
        self.get('facility-list')
        with CaptureQueriesContext(connection) as small:
            self.get('facility-list')
        sju = Region.objects.get(pk=9001)
        for i in range(20):
            facility = Facility.objects.create(county_code=10, air_district=sju, facid=100 + i, name=f'EXTRA {i}',
                                               county=self.plant.county, sic_code=4911, sector='power-plants')
            EmissionsRecord.objects.create(facility=facility, year=2024, nox=i + 1)
        cache.clear()
        self.get('facility-list')
        with CaptureQueriesContext(connection) as large:
            self.get('facility-list')
        assert len(large) == len(small)


class FacilityDetailTests(ViewTestCase):
    def detail(self, facility, params=None, status=200):
        response = self.client.get(facility.get_absolute_url(), params or {})
        assert response.status_code == status
        return response.content.decode()

    def test_page(self):
        content = self.detail(self.plant)
        assert 'TEST PLANT' in content
        assert 'Regulated by' in content and 'San Joaquin Valley APCD' in content
        assert 'Report an air pollution problem' in content
        assert 'Glass manufacturing' in content
        assert 'SIC 3221' in content and 'Glass Containers' in content
        assert 'Benzene' in content
        assert 'how emissions are estimated' in content

    def test_eastern_kern_has_phone_but_no_complaints_link(self):
        content = self.detail(self.cement)
        assert 'Eastern Kern APCD' in content
        assert '(661) 862-5250' in content
        assert 'Report an air pollution problem' not in content

    def test_falls_back_to_the_latest_reported_year(self):
        content = self.detail(self.cement, params={'year': 2023})
        assert 'no emissions reported for 2023' in content

    def test_every_pollutant_toggle(self):
        for pollutant in ('nox', 'rog', 'pm', 'pm10', 'sox', 'co', 'tog'):
            self.detail(self.plant, params={'pollutant': pollutant})

    def test_wrong_slug_redirects_to_the_canonical_url(self):
        url = reverse('emissions:facility-detail', args=[self.plant.sqid, 'wrong'])
        response = self.client.get(url, {'year': 2023})
        assert response.status_code == 301
        assert response['Location'] == self.plant.get_absolute_url() + '?year=2023'

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('emissions:facility-redirect', args=[self.plant.sqid]))
        assert response.status_code == 301
        assert response['Location'] == self.plant.get_absolute_url()

    def test_unknown_sqid_is_404(self):
        assert self.client.get(reverse('emissions:facility-detail', args=['nope', 'x'])).status_code == 404
        assert self.client.get(reverse('emissions:facility-redirect', args=['nope'])).status_code == 404


class SectorTests(ViewTestCase):
    def test_list(self):
        content = self.get('sector-list').content.decode()
        assert 'Cement, concrete &amp; minerals' in content
        assert '<svg class="sparkline"' in content

    def test_detail(self):
        content = self.get('sector-detail', 'glass').content.decode()
        assert 'Glass manufacturing' in content
        assert 'TEST PLANT' in content
        assert 'TEST CEMENT' not in content

    def test_unknown_sector_is_404(self):
        self.get('sector-detail', 'nope', status=404)


class AboutTests(ViewTestCase):
    def test_about(self):
        content = self.get('about').content.decode()
        assert 'Total PM' in content
        assert 'Eastern Kern' in content
        assert 'id="carb-estimates"' in content
        assert 'id="minor-sources"' in content


from urllib.parse import parse_qs

from camp.apps.emissions import stats, views


class MapTests(ViewTestCase):
    def test_map_page(self):
        content = self.get('map', params={'toxics': 1, 'sector': 'glass'}).content.decode()
        assert 'class="facility-map"' in content
        assert 'data-mode="full"' in content
        assert '/api/2.0/emissions/facilities/geojson/' in content
        assert 'value="glass" selected' in content

    def test_map_config(self):
        scope = stats.resolve_scope({'county': 'fresno', 'toxics': '1'})
        config = views.facility_map_config(scope, sector='glass')
        assert parse_qs(config['query']) == {'county': ['fresno'], 'toxics': ['1'], 'sector': ['glass']}
        assert config['unit'] == 'lbs'
        assert config['facility_url'].endswith('/facilities/{id}/')
        assert config['highlight'] == '' and config['center'] == ''

    def test_facility_page_has_a_compact_highlighted_map(self):
        content = self.client.get(self.plant.get_absolute_url()).content.decode()
        assert 'data-mode="compact"' in content
        assert f'data-highlight="{self.plant.sqid}"' in content
        assert 'data-center="36.737,-119.787"' in content

    def test_sector_page_map_is_filtered_to_the_sector(self):
        content = self.get('sector-detail', 'glass').content.decode()
        assert 'data-mode="compact"' in content
        assert 'sector=glass' in content

    def test_map_tab(self):
        assert reverse('emissions:map') in self.get('home').content.decode()
