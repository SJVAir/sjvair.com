import csv
import io
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import areas, dairies, dairy_views, views
from camp.apps.emissions.models import DairyHerd
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_dairies import dairy_inventory, make_dairies, make_dairy
from camp.apps.emissions.tests.test_dairies_pages import dairy_map_data
from camp.apps.regions.models import Region

FARAWAY = 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))'
HERD_TITLE = 'Mature dairy cows (solid) and other cattle (dashed) by year'
EMISSIONS_TITLE = 'Dairy cattle ROG, CARB estimate'
DIGESTER_TITLE = 'Dairies with an operating digester'


class DairyAreaTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.fresno_city = Region.objects.get(type=Region.Type.CITY, slug='fresno')
        self.big, self.small, self.closed = make_dairies()

    def get(self, region, params=None, status=200):
        response = self.client.get(region.get_emissions_dairies_url(), params or {})
        assert response.status_code == status, response.status_code
        return response

    def near(self, params=None, status=200):
        response = self.client.get(reverse('emissions:near-me-dairies'), params or {})
        assert response.status_code == status, response.status_code
        return response


class RouteTests(DairyAreaTestCase):
    def test_region_url(self):
        # The fixture's county slug is 'fresno'.
        assert self.fresno.get_emissions_dairies_url() == f'/tools/emissions/region/{self.fresno.sqid}/{self.fresno.slug}/dairies/'

    def test_every_page_type_renders(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        zipcode = make(Region.Type.ZIPCODE, '93656', AROUND_PLANT)
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        for region in (self.fresno, self.fresno_city, cdp, zipcode, tract):
            content = self.get(region, {'year': '2023'}).content.decode()
            assert 'BIG DAIRY' in content, region
            assert 'SMALL DAIRY' not in content, region
        assert self.get(self.fresno).context['section'] == 'dairies'

    def test_other_types_and_retired_tracts_404(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        self.get(retired, status=404)
        other_type = next(region_type for region_type in Region.Type if region_type not in views.AREA_PAGE_TYPES)
        other = make(other_type, 'Other', AROUND_PLANT)
        assert self.client.get(reverse('emissions:region-dairies', kwargs={'sqid': other.sqid, 'slug': other.slug})).status_code == 404
        assert self.client.get(reverse('emissions:region-dairies-redirect', args=['nope'])).status_code == 404

    def test_short_url_and_wrong_slug_redirect_with_the_query(self):
        target = f'{self.fresno.get_emissions_dairies_url()}?year=2023'
        response = self.client.get(reverse('emissions:region-dairies-redirect', args=[self.fresno.sqid]), {'year': '2023'})
        assert response.status_code == 301 and response['Location'] == target
        response = self.client.get(reverse('emissions:region-dairies', kwargs={'sqid': self.fresno.sqid, 'slug': 'wrong'}), {'year': '2023'})
        assert response.status_code == 301 and response['Location'] == target

    def test_near_me(self):
        content = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Home', 'year': '2023'}).content.decode()
        assert 'Within 1 mile of Home' in content and 'BIG DAIRY' in content
        assert 'class="within' not in content
        assert '3 mi</a>' in content
        home = reverse('emissions:home') + '?find=1'
        for params in ({}, {'lat': 'x', 'lng': '1'}, {'lat': '36.7', 'lng': '-119.7', 'radius': '2'}, {'lat': '47.6', 'lng': '-122.3'}):
            response = self.client.get(reverse('emissions:near-me-dairies'), params)
            assert response.status_code == 302 and response['Location'] == home, params
        long = self.near({'lat': '36.737', 'lng': '-119.787', 'label': 'x' * 500}).content.decode()
        assert 'x' * 121 not in long

    def test_radius_buttons_drop_the_page_number(self):
        # Enough dairies within the radius to paginate, so page=2 is real.
        for n in range(10, 70):
            make_dairy(n, f'DAIRY {n}', (-119.786, 36.736), self.fresno, herds={2023: {'milk_cows': n}})
        dairies.clear_caches()
        content = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023', 'page': '2'}).content.decode()
        scope = re.search(r'<nav class="radius-switcher"[^>]*>(.*?)</nav>', content, re.S).group(1)
        assert 'page=' not in scope
        assert 'radius=3' in scope


class ScopeTests(DairyAreaTestCase):
    def test_a_year_outside_cadd_falls_back_with_a_note(self):
        content = self.get(self.fresno, {'year': '2024'}).content.decode()
        assert 'CADD has herd data for 2022–2023; showing 2023.' in content
        assert 'year=2023' in content and 'year=2024' not in content

    def test_nox_falls_back_to_rog_with_a_note(self):
        content = self.get(self.fresno, {'year': '2023', 'pollutant': 'nox'}).content.decode()
        assert 'Dairies report no NOx; showing ROG.' in content
        assert 'pollutant=rog' in content

    def test_county_is_dropped(self):
        response = self.get(self.fresno_city, {'year': '2023', 'county': 'kern'})
        content = response.content.decode()
        assert 'county=' not in content
        assert 'data-scope="county"' not in content
        assert response.context['county_options'] == []

    def test_disabled_options_have_the_tabs_tooltips(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert 'data-tooltip="CADD has herd data for 2022–2023">2024</span>' in content
        assert 'data-tooltip="CARB reports no NOx from dairy cattle"' in content
        assert 'CARB reports no toxic air contaminants for dairy cattle' in content


class ContentTests(DairyAreaTestCase):
    def test_stat_tiles_match_the_summary(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        summary = dairies.summary(2023, area=areas.RegionArea(self.fresno))
        assert f'<p class="heading">Total dairies</p><p class="title">{summary["dairies"]}</p>' in content
        assert '<p class="heading">Total cattle</p><p class="title">1,600</p>' in content
        assert '<h1 class="title is-3 mb-1">Fresno County</h1>' in content
        assert '<title>Dairies in Fresno County | ' in content

    def test_county_page_has_the_carb_tile_and_chart_and_no_county_column(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.get(self.fresno, {'year': '2023', 'pollutant': 'rog'}).content.decode()
        assert '<p class="heading">Dairy cattle, CARB estimate</p><p class="title">730 <span class="is-size-5">tons/yr ROG</span></p>' in content
        assert '25% of Fresno County ROG' in content
        assert EMISSIONS_TITLE in content and HERD_TITLE in content and DIGESTER_TITLE in content
        # (Not the vacuous '<th>County</th>' check: the header is a sort_link
        # anchor, never a bare <th>County</th>, so that string can never appear.)
        assert '>County <span class="icon' not in content and 'Other cattle' in content
        assert 'CARB estimates dairy emissions by county' not in content

    def test_city_page_has_no_carb_figure_and_links_the_county(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.get(self.fresno_city, {'year': '2023', 'pollutant': 'rog'}).content.decode()
        # (Not a bare "CARB estimate" substring check: the county link line
        # below legitimately reads "CARB estimates dairy emissions...". This
        # catches both the stat tile and the no-dairies line, not just the tile.)
        assert 'Dairy cattle, CARB estimate' not in content and EMISSIONS_TITLE not in content
        assert HERD_TITLE in content and DIGESTER_TITLE in content
        assert f'CARB estimates dairy emissions by county: <a href="{self.fresno.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Fresno County dairies →</a>' in content
        # (The column header is sortable, so it's a sort_link anchor, not a bare <th>County</th>.)
        assert '>County <span class="icon' in content

    def test_county_page_hides_the_county_column(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.get(self.fresno, {'year': '2023', 'pollutant': 'rog'}).content.decode()
        assert '>County <span class="icon' not in content

    def test_ddrdp_tile_on_a_county_page(self):
        from decimal import Decimal

        from camp.apps.emissions.importers import ddrdp
        row = dict(
            project_name='Big Dairy Digester', dairy_name='Big Dairy', city='Riverdale', county='Fresno',
            developer='Dev Co', grant_amount=Decimal('1500000'), end_use='Pipeline injection',
            est_reduction_tco2e=12000.0, awarded=None, operational=None,
        )
        ddrdp.apply(ddrdp.match([row]), '2026-06-27')
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">DDRDP digester grants</p>' in content
        assert '$1,500,000' in content
        city_content = self.get(self.fresno_city, {'year': '2023'}).content.decode()
        assert '<p class="heading">DDRDP digester grants</p>' not in city_content

    def test_summary_and_digester_chart_count_the_same_dairies(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        context = self.get(cdp, {'year': '2023'}).context
        assert context['summary']['dairies'] == 1 and context['summary']['digesters'] == 1
        by_year = {row['year']: row['digesters'] for row in context['digester_trend']}
        assert by_year[2023] == 1
        assert context['trend'] == dairies.trend(area=areas.RegionArea(cdp))

    def test_methane_tile_and_filter_on_an_area_page(self):
        from camp.apps.emissions.importers import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH)])
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">With observed methane plumes</p><p class="title">1</p>' in content
        assert self.get(self.fresno, {'year': '2023', 'methane': '1'}).context['summary']['dairies'] == 1

    def test_table_sorts_searches_and_pages(self):
        # cadd_ids 1-3 are make_dairies()'s; 60 more Fresno dairies make two pages.
        for n in range(10, 70):
            make_dairy(n, f'DAIRY {n}', (-119.786, 36.736), self.fresno, herds={2023: {'milk_cows': n}})
        dairies.clear_caches()
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('DAIRY 69')
        assert 'page=2' in content
        assert f'class="dairy-zoom" data-dairy="{self.big.sqid}"' in content
        content = self.get(self.fresno, {'year': '2023', 'sort': 'name'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('DAIRY 10')
        # The inactive Mature dairy cows header (not a TEXT_SORT_KEY) links
        # to its own descending default first, same as test_dairies_pages.py's
        # tab equivalent.
        assert 'sort=-mature_cows' in content
        content = self.get(self.fresno, {'year': '2023', 'q': 'big'}).content.decode()
        assert 'BIG DAIRY' in content and 'DAIRY 10' not in content
        # (Not a bare "entity-picker" substring check: base.html always
        # links entity-picker.js; the area page's own filter form has no
        # region picker or radius-remove tag -- the area itself is the filter.)
        assert 'class="field entity-picker"' not in content and 'Remove the distance filter' not in content

    def test_csv(self):
        response = self.get(self.fresno, {'year': '2023', 'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        assert f'dairies-{self.fresno.slug}-2023.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['dairy'] for row in rows] == ['BIG DAIRY']
        response = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023', 'format': 'csv'})
        assert 'dairies-near-36.7370--119.7870-1-2023.csv' in response['Content-Disposition']

    def test_no_dairies_this_year_keeps_the_charts(self):
        # CLOSED DAIRY only ever has empty herds; give it one counted year, then none in 2023.
        DairyHerd.objects.filter(dairy=self.closed, year=2021).update(milk_cows=10, mature_cows=10)
        west = make(Region.Type.CDP, 'Westside', 'MULTIPOLYGON(((-119.79 36.738, -119.77 36.738, -119.77 36.75, -119.79 36.75, -119.79 36.738)))')
        dairies.clear_caches()
        content = self.get(west, {'year': '2023'}).content.decode()
        # Westside is a CDP (a community region): dairies_label matches the
        # title tag and breadcrumb, which already add the type for it.
        assert "No dairies in CARB's dairy database in Westside (Community) for 2023." in content
        # (Not a bare "dairy-map" substring check: base.html always links the
        # dairy-map.js script; the container class is what actually renders.)
        assert 'stat-row' not in content and 'dairy-table' not in content and 'class="dairy-map' not in content
        assert HERD_TITLE in content

    def test_no_dairies_ever_has_no_charts(self):
        urban = make(Region.Type.URBAN_AREA, 'Faraway', FARAWAY)
        content = self.get(urban, {'year': '2023'}).content.decode()
        # Faraway is an urban area (a community region): dairies_label
        # matches the title tag and breadcrumb, which already add the type.
        assert "No dairies in CARB's dairy database in Faraway (Urban area) for 2023." in content
        assert HERD_TITLE not in content

    def test_no_dairies_near_me_has_no_charts(self):
        # In Kern (IN_KERN is SMALL DAIRY's location), but 1.4+ miles from it,
        # so it's outside a 1 mile radius while the point is still covered.
        content = self.near({'lat': '35.39', 'lng': '-119.02', 'radius': '1', 'label': 'Home', 'year': '2023'}).content.decode()
        assert "No dairies in CARB's dairy database within 1 mile of Home for 2023." in content
        assert HERD_TITLE not in content

    def test_no_cadd_data_at_all(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        content = self.get(self.fresno).content.decode()
        assert 'No dairy data has been loaded yet.' in content
        assert 'stat-row' not in content

    def test_in_and_around_links_dairy_pages_and_is_cached_apart(self):
        # scope_qs is the dairies scope: the year always, and the (fallen-back) pollutant.
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        section = re.search(r'<section class="within mt-6" id="in-and-around">(.*?)</section>', content, re.S).group(1)
        assert f'href="{self.fresno_city.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog"' in section
        assert '/tools/emissions/region/' in section and '/dairies/' in section
        assert cache.get(f'{views.WITHIN_DAIRIES_KEY}:{self.fresno.pk}') is not None
        assert cache.get(f'{views.WITHIN_KEY}:{self.fresno.pk}') is None

    def test_breadcrumbs(self):
        content = self.get(self.fresno_city, {'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', content, re.S).group(1)
        assert f'<a href="{self.fresno.get_emissions_url()}?year=2023&amp;pollutant=rog">Fresno County</a>' in crumbs
        assert f'<a href="{self.fresno_city.get_emissions_url()}?year=2023&amp;pollutant=rog">Fresno (City)</a>' in crumbs
        assert '<li class="is-active"><a aria-current="page">Dairies</a></li>' in crumbs
        county = self.get(self.fresno, {'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', county, re.S).group(1)
        assert crumbs.count('Fresno County') == 1
        near = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '3', 'label': 'near Home', 'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', near, re.S).group(1)
        assert f'<a href="{reverse("emissions:near-me")}?lat=36.7370&amp;lng=-119.7870&amp;radius=3&amp;label=near+Home&amp;year=2023&amp;pollutant=rog">Within 3 miles of Home</a>' in crumbs
        # Not "<title>Dairies in Within 3 miles of Home" -- the near-me phrase reads mid-sentence.
        assert '<title>Dairies within 3 miles of Home | ' in near

    def test_county_dairy_page_has_the_epa_ammonia_tile(self):
        from camp.apps.emissions import nei
        from camp.apps.emissions.models import CountyNEI
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.LIVESTOCK_SECTOR, tons=8000)
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.FERTILIZER_SECTOR, tons=2000)
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.LIVESTOCK_SECTOR, subsector=nei.DAIRY_SUBSECTOR, tons=4000)
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">Ammonia, EPA estimate</p><p class="title">4,000 <span class="is-size-5">tons/yr</span></p>' in content
        assert 'dairy cattle, 40% of the county&#x27;s ammonia (2023)' in content or "dairy cattle, 40% of the county's ammonia (2023)" in content
        # Not on a city's dairy page, and not without rows.
        assert 'Ammonia, EPA estimate' not in self.get(self.fresno_city, {'year': '2023'}).content.decode()
        assert 'Ammonia, EPA estimate' not in self.get(self.kern, {'year': '2023'}).content.decode()


class MapConfigTests(DairyAreaTestCase):
    def test_region_page_map(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert dairy_map_data(content, 'view') == 'dairies'
        assert 'data-view="counties"' not in content
        assert dairy_map_data(content, 'outline-url') == reverse('api:v2:regions:region-detail', args=[self.fresno.sqid])
        assert dairy_map_data(content, 'geojson-url') == f'/api/2.0/emissions/dairies/geojson/?year=2023&amp;region={self.fresno.sqid}'
        assert dairy_map_data(content, 'county') in ('', None)
        assert 'data-size="large"' in content and 'data-digester="yes"' in content

    def test_near_me_map(self):
        content = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '3', 'year': '2023'}).content.decode()
        assert dairy_map_data(content, 'center') == '36.7370,-119.7870'
        assert dairy_map_data(content, 'zoom') == '12'
        assert dairy_map_data(content, 'radius') == '3'
        assert dairy_map_data(content, 'geojson-url') == '/api/2.0/emissions/dairies/geojson/?year=2023&amp;lat=36.7370&amp;lng=-119.7870&amp;radius=3'

    def test_config(self):
        scope, _ = dairies.resolve_scope({'year': '2023'})
        config = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({}), area_params={'region': 'abc'}, outline_url='/o/')
        assert config['view'] == 'dairies' and config['view_options'] == ()
        assert config['map']['data']['outline-url'] == '/o/'
        tab = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({'view': 'counties'}))
        assert tab['view'] == 'counties' and tab['view_options'] == dairy_views.VIEW_OPTIONS
