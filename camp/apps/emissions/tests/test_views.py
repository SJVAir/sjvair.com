import csv
import io
import re

from types import SimpleNamespace

from urllib.parse import parse_qs

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.apps.emissions import cepam, stats, views
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility, ToxicPollutant
from camp.apps.regions.models import Region


def map_data(content, key):
    """
    A map container's data-{key} value, whichever kind of map rendered the
    page (facility-map or dairy-map): shared by the overlay tests
    (test_methane.py), which check both kinds of page.
    """
    match = re.search(rf'class="(?:facility|dairy)-map map-canvas"[^>]*data-{key}="([^"]*)"', content)
    return match.group(1) if match else None


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
    def test_the_stats_row_is_derived_not_counts(self):
        # The entry cards carry the counts; the stats row the total, its change, and its concentration.
        content = self.get('home').content.decode()
        row = content[content.index('class="level stat-row box"'):]
        row = row[:row.index('<hr') if '<hr' in row[:4000] else row.index('home-counties')]
        assert "Top 10 facilities' share" in row and "Largest sector's share" in row and "Largest county's share" in row
        assert 'Facilities reporting' not in row and 'Tracked by EPA' not in row

    def test_renders_for_every_scope(self):
        for params in ({}, {'year': 2023}, {'county': 'fresno'}, {'county': 'kern', 'toxics': 1},
                       {'minor': 1}, {'pollutant': 'pm'}, {'year': 1900, 'pollutant': 'bogus'},
                       {'toxics': 1, 'pollutant': 'diesel-pm'}, {'toxics': 1, 'pollutant': 'chronic'},
                       {'pollutant': 'nh3'}, {'pollutant': 'nh3', 'county': 'fresno'}):
            self.get('home', params=params)

    def test_top_facilities_and_totals(self):
        response = self.get('home')
        content = response.content.decode()
        assert 'Test Cement' in content
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

    def test_entry_cards(self):
        response = self.get('home')
        cards = response.context['entry_cards']
        assert [card['title'] for card in cards] == ['Facilities', 'Dairies', 'Oil & gas', 'Schools']
        facilities, dairies, oil_gas, schools = cards
        # Facilities: the scope year's count, same as the stat row above the cards.
        assert facilities['value'] == response.context['totals']['facilities'] > 0
        assert facilities['url'] == reverse('emissions:facility-list')
        # Dairies and Oil & gas have no fixture data here, so their counts are 0 -- still present, not errors.
        assert dairies['value'] == 0
        assert dairies['url'] == reverse('emissions:dairy-list')
        assert oil_gas['value'] == 0
        assert oil_gas['url'] == reverse('emissions:oil-gas')
        assert schools['url'] == '#find-area'
        assert isinstance(schools['value'], int)
        content = response.content.decode()
        assert 'entry-card' in content and 'Pick your area to see its schools' in content

    def test_county_table_and_map(self):
        response = self.get('home')
        rows = response.context['county_rows']
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        # Most to least NOx, then every other county at the bottom with none.
        assert [row['county'] for row in rows[:2]] == [kern, fresno]
        assert rows[0]['value'] == 100 and rows[1]['value'] == 6
        assert {row['county'] for row in rows} == set(Region.objects.counties())
        # Darkest for the most; the no-data gray for any county with none.
        assert rows[0]['color'] != rows[1]['color']
        assert all(row['value'] == 0 and row['color'] == '#f0f0f0' for row in rows[2:])
        content = response.content.decode()
        assert f'data-county="{kern.sqid}"' in content
        assert f'href="{kern.get_emissions_url()}">Kern</a>' in content
        assert 'class="county-map"' in content

    def test_county_links_keep_the_scope_but_not_the_county(self):
        content = self.get('home', params={'year': 2023, 'county': 'fresno'}).content.decode()
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        assert f'href="{kern.get_emissions_url()}?year=2023">Kern</a>' in content

    def test_biggest_movers(self):
        movers = self.get('home').context['movers']
        assert (movers['year_from'], movers['year_to']) == (2023, 2024)
        rising, falling = movers['groups']
        # TEST CEMENT is new to NOx in 2024 (no percentage); TEST PLANT doubled.
        assert [(row['facility'], row['change'], row['pct']) for row in rising['rows']] == [
            (self.cement, 100, None), (self.plant, 3, 100),
        ]
        assert falling['rows'] == []
        content = self.get('home').content.decode()
        assert 'Biggest movers · 2023 to 2024' in content and 'Nothing fell.' in content
        assert '+100</td>' in content and '>new</td>' in content and '+100%' in content

    def test_no_movers_for_the_first_year(self):
        assert self.get('home', params={'year': 2023}).context['movers'] is None

    def hero_classes(self, url):
        html = self.client.get(url).content.decode()
        tag = re.search(r'<section\b[^>]*\bid="explorer-hero"[^>]*>', html).group(0)
        return re.search(r'class="([^"]*)"', tag).group(1).split()

    def test_home_renders_the_full_hero(self):
        assert 'is-compact' not in self.hero_classes(reverse('emissions:home'))

    def test_inner_pages_render_the_compact_hero(self):
        for name in ('emissions:map', 'emissions:facility-list'):
            assert 'is-compact' in self.hero_classes(reverse(name))


class ExplorerMarkupTests(ViewTestCase):
    def test_dropdowns_are_not_aria_menus(self):
        html = self.get('map').content.decode()
        assert 'role="menu"' not in html and 'role="menuitem"' not in html

    def test_one_h1_per_page(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        for url in (
            reverse('emissions:home'),
            reverse('emissions:map'),
            reverse('emissions:facility-list'),
            reverse('emissions:sector-list'),
            reverse('emissions:about'),
            reverse('emissions:dairy-list'),
            reverse('emissions:oil-gas'),
            fresno.get_emissions_url(),
            self.plant.get_absolute_url(),
        ):
            html = self.client.get(url).content.decode()
            assert len(re.findall(r'<h1[\s>]', html)) == 1, url


class FacilityListTests(ViewTestCase):
    def test_list_shows_the_cased_name_not_carbs_raw_one(self):
        content = self.get('facility-list').content.decode()
        assert 'Test Plant' in content and 'Test Cement' in content
        assert 'TEST PLANT' not in content and 'TEST CEMENT' not in content

    def test_filters_and_sort(self):
        assert 'Test Plant' in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST CEMENT' not in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST PLANT' not in self.get('facility-list', params={'sector': 'cement-minerals'}).content.decode()
        self.get('facility-list', params={'sort': 'name', 'region': 'nosuchregion', 'page': 99})

    def test_minor_sources_only_when_asked(self):
        assert 'TEST GAS STATION' not in self.get('facility-list').content.decode()
        assert 'Test Gas Station' in self.get('facility-list', params={'minor': 1, 'pollutant': 'rog'}).content.decode()

    def test_csv(self):
        response = self.get('facility-list', params={'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        assert 'facility-emissions-2024.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['facility'] for row in rows] == ['TEST CEMENT', 'TEST PLANT']
        assert rows[0]['rank'] == '1'
        assert rows[0]['air_district'] == 'Eastern Kern APCD'
        assert float(rows[0]['nox_tons']) == 100.0

        rows = list(csv.DictReader(io.StringIO(
            self.get('facility-list', params={'format': 'csv', 'toxics': 1, 'pollutant': 'benzene'}).content.decode())))
        assert float(rows[0]['benzene_lbs']) == 2.0 and rows[0]['facility'] == 'TEST PLANT'
        assert 'benzene_lbs' not in list(csv.DictReader(io.StringIO(
            self.get('facility-list', params={'format': 'csv'}).content.decode())))[0]

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

    def test_page_shows_the_cased_name_not_carbs_raw_one(self):
        content = self.detail(self.plant)
        assert '<h1 class="mb-1">Test Plant</h1>' in content
        assert '<title>Test Plant |' in content
        assert 'TEST PLANT' not in content

    def test_page(self):
        content = self.detail(self.plant)
        assert 'Test Plant' in content
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
        assert 'Test Plant' in content
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
        assert 'id="weighted-toxics"' in content and 'Consolidated Table' in content


class MapTests(ViewTestCase):
    def test_map_page(self):
        content = self.get('map', params={'toxics': 1, 'sector': 'glass'}).content.decode()
        assert 'class="facility-map map-canvas"' in content
        assert 'data-mode="full"' in content
        assert '/api/2.0/emissions/facilities/geojson/' in content
        # Which facilities is the filter box's: search, Search by location, then the sector.
        box = content[content.index('class="explorer-filters box"'):content.index('</form>', content.index('class="explorer-filters box"'))]
        assert box.index('id="map-q"') < box.index('Search by location') < box.index('id="map-sector"')
        assert '<option value="glass" selected>' in box
        assert 'sector=glass' in content  # the map's data query
        assert 'data-sector=' not in content  # no sector dropdown in the toolbar
        # The core's chrome: the toolbar, expand button and legend card, and
        # (for when the filter box is out of sight) the Filters button, its slide-out and chips.
        assert 'class="map-toolbar-filters"' in content
        assert 'class="button map-filters-toggle"' in content and 'class="map-filters-panel"' in content and 'class="map-filter-chips"' in content
        assert 'class="button map-expand"' in content
        assert 'map-legend-panel' in content
        assert 'class="facility-map-legend"' in content
        # The options dropdown is named as on the pesticides maps.
        assert '<span class="map-toolbar-label">Tweaks</span>' in content
        assert 'fa-flask-gear' in content

    def test_map_page_search_narrows_the_facilities(self):
        content = self.get('map', params={'q': 'cement'}).content.decode()
        assert 'q=cement' in content and 'value="cement"' in content

    def test_map_page_has_the_areas_controls(self):
        content = self.get('map', params={'view': 'areas', 'level': 'tract'}).content.decode()
        assert 'data-view="facilities"' in content and 'data-view="areas"' in content
        assert 'data-level="tract"' in content and 'data-measure="per_resident"' in content
        assert 'data-areas="1"' in content

    def test_region_pages_have_the_switch_but_no_sector_filter(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        content = self.client.get(fresno.get_emissions_url()).content.decode()
        assert 'data-view="areas"' in content
        assert 'facility-map-sector' not in content

    def test_facility_pages_have_no_areas_controls(self):
        content = self.client.get(self.plant.get_absolute_url()).content.decode()
        assert 'data-view="areas"' not in content
        assert 'data-default-level=""' in content

    def test_map_page_default_level(self):
        content = self.get('map', params={'view': 'areas', 'level': 'county'}).content.decode()
        assert 'data-level="county"' in content and 'data-default-level="tract"' in content

    def test_map_view_carries_its_default_level(self):
        assert views.map_view({'level': 'tract'}, 'zipcode')['default_level'] == 'zipcode'
        assert views.map_view({})['default_level'] == 'tract'

    def test_map_view_compare_and_compare_options(self):
        # No year to compare against: neither a compare nor any options,
        # whatever the request asks for.
        result = views.map_view({'compare': '2023'}, year=None)
        assert result['compare'] == '' and result['compare_options'] == []
        # A year to compare against: every other loaded year is an option,
        # newest first, and a valid request resolves.
        result = views.map_view({'compare': '2023'}, year=2024)
        assert result['compare'] == 2023 and result['compare_options'] == [2023]
        # The scope year itself and an unloaded year both resolve to nothing.
        assert views.map_view({'compare': '2024'}, year=2024)['compare'] == ''
        assert views.map_view({'compare': '1999'}, year=2024)['compare'] == ''
        assert views.map_view({}, year=2024)['compare'] == ''

    def test_compact_maps_have_no_sector_filter(self):
        content = self.get('sector-detail', 'glass').content.decode()
        assert 'map-wrap is-compact' in content
        assert 'map-toolbar-filters' not in content
        assert 'class="button map-expand"' in content

    def test_map_config_carries_the_include(self):
        config = views.facility_map_config(stats.resolve_scope({}), mode='compact')
        assert config['map']['compact'] is True
        assert config['map']['toolbar_template'] is None
        assert config['map']['data']['bounds'] == config['bounds']
        assert config['map']['data']['geojson-url'] == config['geojson_url']
        assert 'sector' not in config['map']['data']

    def test_map_config(self):
        scope = stats.resolve_scope({'county': 'fresno', 'toxics': '1'})
        config = views.facility_map_config(scope, sector='glass')
        assert parse_qs(config['query']) == {'county': ['fresno'], 'toxics': ['1'], 'sector': ['glass']}
        assert config['unit'] == 'share'
        assert config['facility_url'].endswith('/facilities/{id}/')
        assert config['highlight'] == '' and config['center'] == ''

    def test_map_opens_on_the_covered_counties(self):
        config = views.facility_map_config(stats.resolve_scope({}))
        west, south, east, north = (float(value) for value in config['bounds'].split(','))
        assert west < -119.787 < east
        assert south < 36.737 < north
        assert 'data-bounds="' + config['bounds'] + '"' in self.get('map').content.decode()

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

    def map_query(self, content):
        match = re.search(r'data-query="([^"]*)"', content)
        assert match, 'no data-query attribute found'
        return match.group(1)

    def test_facility_page_map_always_includes_a_minor_source(self):
        # The page scope defaults to major sources only; the gas station is a
        # minor source, so its own map must force minor=1 or it can't show up.
        gas_station = Facility.objects.get(name='TEST GAS STATION')
        content = self.client.get(gas_station.get_absolute_url()).content.decode()
        assert 'minor=1' in self.map_query(content)

    def test_facility_page_map_ignores_a_different_county_scope(self):
        # TEST CEMENT is in Kern; viewing it with ?county=fresno must not
        # carry that county into its own map query, or the facility drops out.
        content = self.client.get(self.cement.get_absolute_url(), {'county': 'fresno'}).content.decode()
        assert 'county=' not in self.map_query(content)


class ToxicsPagesTests(ViewTestCase):
    def test_legacy_toxic_key_redirects(self):
        # Benzene's slug happens to equal its old key; a renamed slug shows the redirect for real.
        ToxicPollutant.objects.filter(carb_id='71432').update(slug='benzene-2')
        response = self.client.get(reverse('emissions:home'), {'toxics': 1, 'pollutant': 'benzene', 'year': 2024})
        assert response.status_code == 301
        location = response['Location']
        assert location.startswith(reverse('emissions:home') + '?')
        assert parse_qs(location.split('?', 1)[1]) == {'toxics': ['1'], 'pollutant': ['benzene-2'], 'year': ['2024']}
        # Not a toxics scope, or not an old key: no redirect.
        assert self.client.get(reverse('emissions:facility-list'), {'pollutant': 'benzene'}).status_code == 200
        assert self.client.get(reverse('emissions:facility-list'), {'toxics': 1, 'pollutant': 'benzene-2'}).status_code == 200

    def test_picker_lists_weighted_measures_then_toxics(self):
        content = self.get('home', params={'toxics': 1}).content.decode()
        assert content.index('pollutant=chronic') < content.index('pollutant=diesel-pm') < content.index('pollutant=benzene')
        assert 'pollutant=ammonia' not in content
        assert '<span class="explorer-scope-label">Cancer-weighted</span>' in content

    def test_home_shows_shares_and_the_breakdown(self):
        content = self.get('home', params={'toxics': 1}).content.decode()
        assert "Share of the Valley's cancer-weighted toxics" in content
        # (23.1 + 0.4466) / 23.65825 = 0.99528, minor sources off; share_pct
        # rounds a >=10% share to a whole percent, so this reads "100%" (the
        # breakdown card below spells out that it's not the full total).
        assert '100%' in content
        assert 'What drives it' in content and 'Diesel PM' in content
        assert 'share/yr' not in content and 'share of Valley total</span>' not in content

    def test_region_page_shows_the_breakdown_and_no_per_square_mile(self):
        # The stat row (before the map wrap -- the toolbar now comes before the
        # map canvas in the DOM for keyboard focus order, and its measure dropdown
        # keeps "Per square mile" as a disabled option's label) is where the tile
        # itself would appear.
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        content = self.client.get(kern.get_emissions_url(), {'toxics': 1}).content.decode()
        stat_row = content[:content.index('class="map-wrap')]
        assert 'What drives it' in content and 'Per square mile' not in stat_row
        content = self.client.get(kern.get_emissions_url()).content.decode()
        stat_row = content[:content.index('class="map-wrap')]
        assert 'What drives it' not in content and 'Per square mile' in stat_row

    def test_share_measures_are_disabled(self):
        content = self.get('map', params={'toxics': 1, 'view': 'areas', 'measure': 'density'}).content.decode()
        # Only Total is a live item; density and per-resident are disabled spans with the tooltip.
        assert re.search(r'class="dropdown-item is-active" data-measure="total"', content)
        assert 'data-measure="density"' not in content and 'data-measure="per_resident"' not in content
        assert content.count(views.SHARE_MEASURE_TOOLTIP) == 2
        assert 'data-unit="share"' in content and 'data-measure="total"' in content
        assert views.map_view({'measure': 'density'}, year=2024, share=True)['measure'] == 'total'
        plain = self.get('map', params={'view': 'areas'}).content.decode()
        assert 'data-measure="density"' in plain and views.SHARE_MEASURE_TOOLTIP not in plain


class AmmoniaPagesTests(ViewTestCase):
    def test_picker_lists_ammonia_under_a_precursor_heading(self):
        content = self.get('home').content.decode()
        assert 'pollutant=nh3' in content and 'pollutant=nh3' not in self.get('home', params={'toxics': 1}).content.decode()
        heading = content.index('explorer-scope-group">Precursor')
        assert content.index('pollutant=tog') < heading < content.index('pollutant=nh3')
        assert '<span class="has-text-grey">Ammonia</span>' in content

    def test_ammonia_scope_pages(self):
        content = self.get('home', params={'pollutant': 'nh3'}).content.decode()
        assert '<span class="explorer-scope-label">NH3</span>' in content and 'tons/yr' in content
        assert 'CARB estimates all sources' not in content  # CEPAM has no ammonia
        self.get('map', params={'pollutant': 'nh3'})
        self.get('sector-detail', 'glass', params={'pollutant': 'nh3'})
        content = self.get('facility-list', params={'pollutant': 'nh3'}).content.decode()
        assert 'NH3 (tons/yr)' in content

    def test_csv_carries_an_nh3_tons_column(self):
        rows = list(csv.DictReader(io.StringIO(self.get('facility-list', params={'format': 'csv', 'pollutant': 'nh3'}).content.decode())))
        assert float(rows[0]['nh3_tons']) == 0.05 and rows[0]['facility'] == 'TEST PLANT'
        assert 'nh3_tons' not in list(csv.DictReader(io.StringIO(self.get('facility-list', params={'format': 'csv'}).content.decode())))[0]


class UniformColumnsTests(TestCase):
    def rows(self, *places):
        return [
            (n, SimpleNamespace(facility=SimpleNamespace(city_id=city, county_id=county, address={'city': 'X'})))
            for n, (city, county) in enumerate(places, 1)
        ]

    def test_a_column_every_row_repeats_is_hidden(self):
        assert views.uniform_columns(self.rows((1, 10), (1, 10))) == {'hide_city': True, 'hide_county': True}
        assert views.uniform_columns(self.rows((1, 10), (2, 10))) == {'hide_city': False, 'hide_county': True}
        assert views.uniform_columns(self.rows((1, 10), (2, 11))) == {'hide_city': False, 'hide_county': False}

    def test_one_row_keeps_every_column(self):
        assert views.uniform_columns(self.rows((1, 10))) == {'hide_city': False, 'hide_county': False}
        assert views.uniform_columns([]) == {'hide_city': False, 'hide_county': False}


class PageOfTests(TestCase):
    """views.page_of: Paginator.get_page, except a zero or negative page is the first (as pesticides' lists)."""

    def test_pages(self):
        from camp.apps.emissions.views import PAGE_SIZE, page_of
        rows = list(range(PAGE_SIZE * 3))
        assert page_of(rows, '2').number == 2
        assert page_of(rows, '0').number == 1 and page_of(rows, '-4').number == 1
        assert page_of(rows, 'junk').number == 1 and page_of(rows, None).number == 1
        assert page_of(rows, '99').number == 3
