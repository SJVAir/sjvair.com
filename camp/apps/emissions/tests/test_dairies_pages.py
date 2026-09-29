import csv
import io
import json
import re

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import areas, dairies, dairy_views
from camp.apps.emissions.models import DairyHerd, Facility
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_areas_pages import map_data
from camp.apps.emissions.tests.test_dairies import IN_KERN, dairy_inventory, make_dairies, make_dairy
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
        assert '<p class="heading">Total dairies</p><p class="title">2</p>' in content
        assert '1 large dairy<' in content
        assert '<p class="heading">Milk cows</p><p class="title">1,200</p>' in content
        assert '<p class="heading">Total cattle</p><p class="title">1,750</p>' in content
        assert '<p class="heading">With a digester</p><p class="title">1</p>' in content
        assert '50% of dairies' in content
        assert '69% of cattle' in content
        assert 'CAFO' not in content.split('stat-row')[1].split('</div>\n</div>')[0]

    def test_the_county_narrows_the_numbers_the_table_and_the_map(self):
        content = self.get({'county': 'kern'}).content.decode()
        assert 'SMALL DAIRY' in content and 'BIG DAIRY' not in content
        assert '<p class="heading">Total dairies</p><p class="title">1</p>' in content
        assert dairy_map_data(content, 'county') == 'kern'

    def test_table(self):
        content = self.get().content.decode()
        assert content.index('BIG DAIRY') < content.index('SMALL DAIRY')
        assert 'CLOSED DAIRY' not in content
        assert f'class="dairy-zoom" data-dairy="{self.big.sqid}" data-lng="-119.78500" data-lat="36.73500"' in content
        assert 'Yes, since 2019' in content
        assert '>Mature dairy cows</a>' in content and '<th>EPA size</th>' in content
        big_row = content[content.index('BIG DAIRY</a>'):]
        big_row = big_row[:big_row.index('</tr>')]
        assert re.findall(r'<td[^>]*>([^<]*)</td>', big_row)[1:4] == ['1,300', '300', 'Large']
        assert f'href="{self.fresno.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog"' in content
        content = self.get({'sort': 'name'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('SMALL DAIRY')
        assert 'sort=-mature_cows' in content
        content = self.get({'q': 'small'}).content.decode()
        assert 'SMALL DAIRY' in content and 'BIG DAIRY' not in content

    def test_digester_with_unknown_start_year(self):
        # A handful of CADD's AgSTAR digesters carry no recorded start year.
        make_dairy(4, 'AGSTAR DAIRY', IN_KERN, self.kern, herds={2023: {'milk_cows': 50}}, digesters=[(None, None)])
        dairies.clear_caches()
        content = self.get().content.decode()
        assert 'Yes (start year unknown)' in content
        assert 'since None' not in content and 'since null' not in content

    def test_a_region_redirects_to_its_dairy_page(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        response = self.client.get(self.url, {'region': cdp.sqid, 'year': '2023', 'sort': 'name', 'view': 'counties', 'measure': 'mature_cows'})
        assert response.status_code == 301
        assert response['Location'] == f'{cdp.get_emissions_dairies_url()}?year=2023&sort=name&measure=mature_cows'
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        assert self.client.get(self.url, {'region': tract.sqid})['Location'] == tract.get_emissions_dairies_url()
        assert self.client.get(self.url, {'region': self.fresno.sqid})['Location'] == self.fresno.get_emissions_dairies_url()

    def test_an_unknown_region_renders_unfiltered(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        for sqid in ('nope', retired.sqid):
            content = self.get({'region': sqid}).content.decode()
            assert 'BIG DAIRY' in content and 'SMALL DAIRY' in content

    def test_an_unknown_region_falls_back_to_a_valid_point(self):
        # ?region= that doesn't resolve, alongside a usable point: try the
        # point instead of rendering unfiltered.
        params = {'region': 'nope', 'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023'}
        response = self.client.get(self.url, params)
        assert response.status_code == 301
        assert response['Location'] == f"{reverse('emissions:near-me-dairies')}?lat=36.737&lng=-119.787&radius=1&year=2023"

    def test_a_point_redirects_to_the_near_me_dairy_page(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Tower District', 'year': '2023'}
        response = self.client.get(self.url, params)
        assert response.status_code == 301
        assert response['Location'] == f"{reverse('emissions:near-me-dairies')}?lat=36.737&lng=-119.787&radius=1&label=near+Tower+District&year=2023"
        # A radius near-me doesn't offer is no filter at all: the tab renders.
        content = self.get({**params, 'radius': '2'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' in content

    def test_redirect_drops_the_page_number(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        response = self.client.get(self.url, {'region': cdp.sqid, 'year': '2023', 'page': '4'})
        assert response.status_code == 301
        assert response['Location'] == f'{cdp.get_emissions_dairies_url()}?year=2023'
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023', 'page': '4'}
        response = self.client.get(self.url, params)
        assert response.status_code == 301
        assert response['Location'] == f"{reverse('emissions:near-me-dairies')}?lat=36.737&lng=-119.787&radius=1&year=2023"

    def test_a_valid_region_drops_the_point_params(self):
        # region= wins over lat/lng/radius/label when both are given; they
        # don't do anything on the region's own dairy page, so drop them.
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        params = {
            'region': cdp.sqid, 'lat': '36.737', 'lng': '-119.787', 'radius': '1',
            'label': 'near Home', 'year': '2023',
        }
        response = self.client.get(self.url, params)
        assert response.status_code == 301
        assert response['Location'] == f'{cdp.get_emissions_dairies_url()}?year=2023'

    def test_find_box_points_at_dairy_pages(self):
        content = self.get({'county': 'kern', 'pollutant': 'pm10'}).content.decode()
        # (Not a bare "entity-picker" substring check: base.html always
        # links entity-picker.js; the tab's own filter form has no picker.)
        assert 'class="field entity-picker"' not in content
        assert f'data-near-url="{reverse("emissions:near-me-dairies")}"' in content
        places = json.loads(re.search(r'id="find-area-places"[^>]*>(.*?)</script>', content, re.S).group(1))
        fresno = next(place for place in places if place['name'] == 'Fresno County')
        assert fresno['url'] == self.fresno.get_emissions_dairies_url()
        jumps = re.search(r'<p class="find-area-counties">(.*?)</p>', content, re.S).group(1)
        hrefs = re.findall(r'href="([^"]*)"', jumps)
        assert hrefs and all('/dairies/?' in href and 'county=' not in href and 'pollutant=pm10' in href for href in hrefs)

    def test_csv(self):
        response = self.client.get(self.url, {'format': 'csv', 'county': 'fresno'})
        assert response['Content-Type'] == 'text/csv'
        assert 'dairies-2023.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['dairy'] for row in rows] == ['BIG DAIRY']
        big = rows[0]
        assert (big['cadd_id'], big['county'], big['milk_cows'], big['beef_cattle']) == ('1', 'Fresno County', '1100', '')
        assert (big['mature_cows'], big['other_cattle'], big['size_class']) == ('1300', '300', 'large')
        assert list(big) == [
            'cadd_id', 'dairy', 'id', 'street', 'city', 'zipcode', 'county', 'year',
            'milk_cows', 'dry_cows', 'old_heifers', 'young_heifers', 'old_calves', 'young_calves', 'beef_cattle',
            'mature_cows', 'other_cattle', 'size_class',
            'milk_cows_ref_code', 'non_milking_ref_code', 'digester_operating', 'digester_since',
        ]
        assert (big['digester_operating'], big['digester_since']) == ('yes', '2019')

    def test_map(self):
        content = self.get().content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('dairies', 'mature_cows')
        assert dairy_map_data(content, 'geojson-url') == '/api/2.0/emissions/dairies/geojson/?year=2023'
        assert 'data-view="counties"' in content and 'data-measure="mature_cows_per_sq_mi"' in content
        assert 'Mature dairy cows per sq mi' in content
        content = self.get({'view': 'counties', 'measure': 'emissions'}).content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('counties', 'emissions')
        content = self.get({'view': 'bogus', 'measure': 'x'}).content.decode()
        assert (dairy_map_data(content, 'view'), dairy_map_data(content, 'measure')) == ('dairies', 'mature_cows')

    def test_map_config(self):
        scope, _ = dairies.resolve_scope({'county': 'kern', 'pollutant': 'pm10'})
        config = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({}))
        assert config['counties_url'].endswith('/dairies/counties/?year=2023&pollutant=pm10')
        assert config['popup_url'].endswith('/dairies/{id}/?year=2023')
        assert (config['county'], config['label']) == ('kern', 'PM10')
        assert config['map']['data']['source-note'] == 'CARB county inventory, dairy cattle: animals and manure only, not feed or silage'
        assert config['map']['container_id'] == 'dairy-map'

    def test_map_sizes_default_is_all_three(self):
        # No `sizes` in the query: every class is on.
        assert dairy_views.dairy_map_view({})['sizes'] == dairy_views.SIZE_VALUES

    def test_map_sizes_drops_unknown_tokens(self):
        view = dairy_views.dairy_map_view({'sizes': 'large,bogus,medium'})
        assert view['sizes'] == {'large', 'medium'}

    def test_map_sizes_blank_means_none_not_default(self):
        # Present but empty (every checkbox unticked) must not fall back to
        # "absent" (every checkbox ticked) -- they're opposite choices.
        assert dairy_views.dairy_map_view({'sizes': ''})['sizes'] == set()

    def test_map_digester_only_yes_or_no_pass_through(self):
        assert dairy_views.dairy_map_view({'digester': 'yes'})['digester'] == 'yes'
        assert dairy_views.dairy_map_view({'digester': 'no'})['digester'] == 'no'
        assert dairy_views.dairy_map_view({'digester': 'maybe'})['digester'] == ''
        assert dairy_views.dairy_map_view({})['digester'] == ''

    def test_map_config_sizes_and_digester(self):
        scope, _ = dairies.resolve_scope({})
        # Canonical (small, medium, large) order regardless of the query's
        # order, and the button labels the toolbar template reads.
        config = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({'sizes': 'large,medium', 'digester': 'yes'}))
        assert config['sizes'] == ['medium', 'large']
        assert config['size_label'] == 'Medium, Large'
        assert (config['digester'], config['digester_label']) == ('yes', 'With a digester')
        assert (config['map']['data']['sizes'], config['map']['data']['digester']) == ('medium,large', 'yes')
        # The default (all sizes, no digester choice): still present on the
        # container (so the map always has something to read), but the
        # toolbar reads it as "All sizes" / "All dairies", not a filter.
        default = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({}))
        assert default['size_label'] == 'All sizes'
        assert default['digester_label'] == 'All dairies'
        assert default['map']['data']['sizes'] == 'small,medium,large'
        assert default['map']['data']['digester'] == ''

    def test_sizes_and_digester_stay_out_of_the_canonical_query_and_its_links(self):
        # A plain visit (no sizes=/digester= in the request) must not have
        # dairy_views.canonical_query() or the page's own links (sort, the
        # scope querystring) invent them from the map_config defaults --
        # the map's filter choices are the map's own client-side state
        # (writeState/M.rewriteQuery), not part of the page's scope.
        content = self.get().content.decode()
        # `[?&]sizes=`, not a bare substring match: the page's favicon links
        # carry their own unrelated `sizes="32x32"` attribute.
        assert not re.search(r'[?&](sizes|digester)=', content)

    def test_coverage_note_before_2019(self):
        DairyHerd.objects.create(dairy=self.big, year=2018, milk_cows=900, mature_cows=900, size_class='large')
        dairies.clear_caches()
        assert 'CADD tracked fewer dairies before 2019' in self.get({'year': '2018'}).content.decode()
        assert 'CADD tracked fewer dairies before 2019' not in self.get().content.decode()

    def test_trend_chart(self):
        content = self.get().content.decode()
        assert 'Mature dairy cows (solid) and other cattle (dashed) by year' in content
        assert '"y": [1200, 1400]' in content and '"y2": [0, 350]' in content

    def test_no_data_yet(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        content = self.get().content.decode()
        assert 'No dairy data has been loaded yet.' in content
        assert 'class="dairy-map map-canvas"' not in content
        assert 'Year: None' not in content
        assert 'data-tooltip=""' not in content

    def test_tab(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert f'href="{self.url}' in content and 'fa-cow' in content


def block_end(content):
    return content.index('</section>', content.index('id="dairies"'))


class DairyBlockTests(DairyPageTestCase):
    """The one-line dairy summary on a region or near-me page, linking the area's dairy page."""

    def region_page(self, region, params=None):
        response = self.client.get(region.get_emissions_url(), params or {})
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def test_county_page(self):
        content = self.region_page(self.fresno, {'year': '2023'})
        block = content[content.index('id="dairies"'):block_end(content)]
        assert '1 dairy · 1,300 mature dairy cows · 1 Large CAFO · 1 with digester' in block
        assert f'<a href="{self.fresno.get_emissions_dairies_url()}?year=2023">Dairies in Fresno County →</a>' in block
        assert 'BIG DAIRY' not in block and 'dairy-table' not in content and 'dairy-charts' not in content

    def test_county_dairy_emissions(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.region_page(self.fresno, {'year': '2023', 'pollutant': 'rog'})
        assert 'Dairy cattle, CARB estimate: <strong>730 tons/yr ROG</strong>' in content
        assert f'href="{self.fresno.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog"' in content
        # NOx (the default): CARB reports none for dairy cattle, and the link leaves the pollutant out.
        content = self.region_page(self.fresno, {'year': '2023'})
        assert '<p class="dairy-county-line is-greyed">No NOx data for dairies.</p>' in content
        assert 'CARB estimate' not in content
        assert f'href="{self.fresno.get_emissions_dairies_url()}?year=2023"' in content

    def test_a_year_outside_cadd_greys_the_block(self):
        content = self.region_page(self.fresno)  # 2024, the explorer's latest year
        assert 'class="dairy-block mt-5 is-greyed"' in content
        assert "No dairy data for 2024. CARB's dairy database covers 2022–2023." in content
        assert f'<a href="{self.fresno.get_emissions_dairies_url()}?year=2023">See 2023 →</a>' in content
        assert '1 dairy ·' not in content and 'Dairies in Fresno County' not in content

    def test_other_region_pages_have_no_county_figure(self):
        dairy_inventory(self.fresno, rog=2.0)
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        content = self.region_page(city, {'year': '2023', 'pollutant': 'rog'})
        assert '1 dairy · 1,300 mature dairy cows · 1 Large CAFO' in content
        assert 'CARB estimate' not in content and 'data for dairies' not in content
        assert f'<a href="{city.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Dairies in Somewhere →</a>' in content

    def test_an_area_without_dairies(self):
        urban = make(Region.Type.URBAN_AREA, 'Faraway', 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))')
        content = self.region_page(urban, {'year': '2023'})
        assert "No dairies in CARB's dairy database here." in content
        assert 'Dairies in Faraway' not in content

    def test_near_me(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Home', 'year': '2023'}
        content = self.client.get(reverse('emissions:near-me'), params).content.decode()
        assert '1 dairy · 1,300 mature dairy cows' in content
        assert f'href="{reverse("emissions:near-me-dairies")}?year=2023&amp;lat=36.7370&amp;lng=-119.7870&amp;radius=1&amp;label=near+Home"' in content
        assert 'CARB estimate' not in content
        # Not "Dairies in Within 1 mile of Home" -- the near-me phrase reads mid-sentence.
        assert 'Dairies within 1 mile of Home →' in content
        assert 'Dairies in Within' not in content

    def test_no_block_before_an_import(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        assert 'id="dairies"' not in self.region_page(self.fresno, {'year': '2023'})


class DairyChartPageTests(DairyPageTestCase):
    """The herd, CARB dairy-cattle emissions and digester charts on the Dairies tab and the region pages' Dairies block."""
    EMISSIONS_TITLE = 'Dairy cattle ROG, CARB estimate'
    HERD_TITLE = 'Mature dairy cows (solid) and other cattle (dashed) by year'
    DIGESTER_TITLE = 'Dairies with an operating digester'

    def region_page(self, region, params):
        response = self.client.get(region.get_emissions_url(), params)
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def test_dairies_tab(self):
        dairy_inventory(self.fresno, year=2022, rog=2.0)
        dairy_inventory(self.fresno, year=2023, rog=1.0)
        content = self.get({'pollutant': 'rog'}).content.decode()
        assert self.HERD_TITLE in content and self.EMISSIONS_TITLE in content and self.DIGESTER_TITLE in content
        assert 'of the covered counties ROG' in content
        assert 'Animals and manure only: CARB counts feed and silage, dairies’ larger ROG source, separately. Years after 2017 are CARB projections.' in content
        county = self.get({'pollutant': 'rog', 'county': 'fresno'}).content.decode()
        assert '% of Fresno County ROG' in county
        # NOx falls back to ROG on the tab, so the chart stays.
        assert self.EMISSIONS_TITLE in self.get({'pollutant': 'nox'}).content.decode()

    def test_dairies_tab_without_digesters(self):
        content = self.get({'county': 'kern'}).content.decode()
        assert self.HERD_TITLE in content
        assert self.DIGESTER_TITLE not in content

    def test_region_and_near_me_pages_have_no_dairy_charts(self):
        # The charts live on the area's dairy page now (test_dairy_area_pages).
        dairy_inventory(self.fresno, year=2023, rog=2.0)
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        for content in (
            self.region_page(self.fresno, {'year': '2023', 'pollutant': 'rog'}),
            self.region_page(city, {'year': '2023', 'pollutant': 'rog'}),
            self.client.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023'}).content.decode(),
        ):
            assert self.HERD_TITLE not in content and self.EMISSIONS_TITLE not in content and self.DIGESTER_TITLE not in content
            assert 'id="dairies"' in content


class SectionNavTests(DairyPageTestCase):
    """The in-page links under a region or near-me page's heading."""

    def nav(self, content):
        match = re.search(r'<nav class="section-nav[^"]*"[^>]*>(.*?)</nav>', content, re.S)
        return match.group(1) if match else None

    def test_county_page(self):
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2023'}).content.decode()
        nav = self.nav(content)
        assert '<a href="#facilities">Facilities</a>' in nav
        assert '<a href="#dairies">Dairies</a>' in nav
        assert '<a href="#in-and-around">In and around</a>' in nav
        for anchor in ('id="facilities"', 'id="dairies"', 'id="in-and-around"'):
            assert anchor in content

    def test_no_dairies_link_outside_cadd_years(self):
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        nav = self.nav(content)
        assert '#dairies' not in nav and '#in-and-around' in nav

    def test_near_me_has_no_in_and_around(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023'}
        nav = self.nav(self.client.get(reverse('emissions:near-me'), params).content.decode())
        assert '#facilities' in nav and '#dairies' in nav
        assert '#in-and-around' not in nav

    def test_nothing_to_jump_to(self):
        # A near-me page with no dairies this year and no "In and around": no nav at all.
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2024'}
        content = self.client.get(reverse('emissions:near-me'), params).content.decode()
        assert self.nav(content) is None


class CombinedMapTests(DairyPageTestCase):
    """
    Dairies were removed from the facility map (region/near-me pages included);
    the Dairies tab (dairy-map.js) is the only place they're mapped. Facility
    maps never carry a dairies URL, in a CADD year or otherwise.
    """

    def test_region_and_near_me_maps_have_no_dairies_url(self):
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2023'}).content.decode()
        assert map_data(content, 'dairies-url') is None
        assert map_data(content, 'dairy-popup-url') is None
        near = self.client.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'year': '2023'}).content.decode()
        assert map_data(near, 'dairies-url') is None

    def test_the_other_maps_have_no_dairies_url_either(self):
        plant = Facility.objects.get(name='TEST PLANT')
        for url in (reverse('emissions:map'), plant.get_absolute_url(), reverse('emissions:sector-detail', args=['glass'])):
            content = self.client.get(url, {'year': '2023'}).content.decode()
            assert map_data(content, 'dairies-url') is None, url


class DairyAboutTests(DairyPageTestCase):
    def test_about_has_a_dairy_section(self):
        # A dairy counted the year before COVERAGE_CHANGE_YEAR and one counted
        # in it, so the two coverage-count figures differ from each other and
        # from the 3 Dairy rows CADD locates (big, small, closed).
        DairyHerd.objects.create(dairy=self.big, year=2018, milk_cows=900, mature_cows=900, size_class='large')
        DairyHerd.objects.create(dairy=self.small, year=2019, milk_cows=50, mature_cows=50, size_class='small')
        dairies.clear_caches()
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert 'id="dairies"' in content
        assert 'https://www.ecfr.gov/current/title-40/chapter-I/subchapter-D/part-122/subpart-B/section-122.23' in content
        assert '<li><strong>Large</strong>: 700 or more mature dairy cows, or 1,000 or more other cattle.</li>' in content
        assert '<li><strong>Medium</strong>: 200–699 mature dairy cows, or 300–999 other cattle.</li>' in content
        assert '<strong>Small</strong>: Fewer than 200 mature dairy cows and 300 other cattle (at least one head of cattle).' in content
        assert 'Feed and silage are left out' in content and '2019' in content and 'reference code' in content
        # The two always-true assertions from the original brief (the tab link
        # is on every page, and "CEPAM 2019" already makes '2019' true) are
        # replaced with the section's own markup.
        assert f'<a href="{reverse("emissions:dairy-list")}">Dairies</a> tab covers what the facility inventory barely sees' in content
        # dairy_count is every imported Dairy row (3), not just the ones with a counted herd.
        assert 'locates every dairy CARB tracks, 3 of them in the eight Valley counties.' in content
        assert "<strong>Coverage grew in 2019.</strong> CADD has herds for 1 Valley dairies in 2018 and 1 in 2019. The two years aren't a like-for-like comparison." in content
        assert 'https://ww2.arb.ca.gov/california-dairy-livestock-database-cadd' in content

    def test_integrations_list_cadd(self):
        content = self.client.get('/about/integrations/').content.decode()
        assert 'California Dairy &amp; Livestock Database' in content


class DairyTableCityLinkTests(DairyPageTestCase):
    def test_a_city_with_a_page_links_to_it(self):
        city = make(Region.Type.CITY, 'Dairyville', AROUND_PLANT)
        make(Region.Type.CDP, 'Dairyville', AROUND_PLANT)
        self.big.address = dict(self.big.address, city='Dairyville')
        self.big.save(update_fields=['address'])
        self.small.address = dict(self.small.address, city='Nowhere Special')
        self.small.save(update_fields=['address'])
        cache.clear()
        content = self.get({'year': 2023}).content.decode()
        # The city wins over a CDP of the same name; a city without a page stays text.
        # The link carries the tab's scope, like the county link beside it.
        assert f'<a href="{city.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Dairyville</a>' in content
        assert '<td>Nowhere Special</td>' in content

    def test_an_aliased_city_links_to_its_cdp_and_keeps_its_name(self):
        cdp = make(Region.Type.CDP, 'Hilmar-Irwin', AROUND_PLANT)
        self.big.address = dict(self.big.address, city='Hilmar')
        self.big.save(update_fields=['address'])
        cache.clear()
        content = self.get({'year': 2023}).content.decode()
        assert f'<a href="{cdp.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Hilmar</a>' in content


class DairyIncludeTests(DairyPageTestCase):
    """The tiles, charts and table the Dairies tab and the dairy region pages share."""

    def test_stats_include_with_and_without_the_carb_tile(self):
        summary = dairies.summary(2023)
        html = render_to_string('emissions/includes/dairy-stats.html', {'summary': summary, 'year': 2023})
        assert '<p class="heading">Total dairies</p><p class="title">2</p>' in html
        assert 'CARB estimate' not in html
        html = render_to_string('emissions/includes/dairy-stats.html', {
            'summary': summary, 'year': 2023, 'pollutant': POLLUTANTS['rog'],
            'carb_estimate': {'tons': 730.0, 'share': 0.25, 'place': 'Fresno County'},
        })
        assert '<p class="heading">Dairy cattle, CARB estimate</p><p class="title">730 <span class="is-size-5">tons/yr ROG</span></p>' in html
        assert '25% of Fresno County ROG' in html

    def test_table_hides_the_county_column(self):
        html = render_to_string('emissions/includes/dairy-table.html', {'rows': [], 'hide_county': True})
        assert '<th>County</th>' not in html
        html = render_to_string('emissions/includes/dairy-table.html', {'rows': []})
        assert '<th>County</th>' in html


class MethaneTests(DairyPageTestCase):
    def setUp(self):
        super().setUp()
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH, rate='120', unc='40')])

    def test_column_filter_and_tile(self):
        content = self.get({'year': '2023'}).content.decode()
        # The column header is sortable, so it's a sort_link anchor (label
        # plus an icon span) rather than a bare <th>Methane observed</th>.
        assert 'sort=-methane_kg_h">Methane observed ' in content and 'Carbon Mapper estimate' in content
        big_row = content[content.index('BIG DAIRY</a>'):]
        assert '120 kg/h' in big_row[:big_row.index('</tr>')]
        assert '<p class="heading">With observed methane plumes</p><p class="title">1</p>' in content
        assert 'name="methane" value="1"' in content and 'With an observed methane source' in content
        assert 'Data by Carbon Mapper' in content
        content = self.get({'year': '2023', 'methane': '1'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content and 'checked' in content

    def test_no_import_shows_nothing(self):
        from camp.apps.emissions import dairies, methane
        from camp.apps.emissions.models import MethaneSource, SourceImport
        MethaneSource.objects.all().delete()
        SourceImport.objects.filter(source='carbon-mapper').delete()
        dairies.clear_caches(); methane.clear_caches()
        content = self.get({'year': '2023'}).content.decode()
        assert 'Methane observed' not in content and 'name="methane"' not in content and 'With observed methane plumes' not in content
