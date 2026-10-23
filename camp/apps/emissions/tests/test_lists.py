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
        content = self.client.get(reverse('emissions:facility-list-table')).content.decode()
        assert 'href="?sort=rank"' in content
        assert 'href="?sort=city"' in content


class RegionFilterTests(ListTestCase):
    """?region= was the list's place filter; a place has its own Facilities tab now, and the old links go there."""

    def test_a_region_redirects_to_its_facilities_tab(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        response = self.client.get(reverse('emissions:facility-list'), {'region': cdp.sqid, 'sector': 'glass', 'page': '2'})
        assert response.status_code == 301
        assert response['Location'] == f"{cdp.get_emissions_tab_url('facilities')}?sector=glass"
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        assert self.client.get(reverse('emissions:facility-list'), {'region': tract.sqid})['Location'].startswith(tract.get_emissions_tab_url('facilities'))

    def test_an_unknown_region_is_ignored(self):
        content = self.client.get(reverse('emissions:facility-list'), {'region': 'nope'}).content.decode()
        assert 'Test Cement' in content and 'Test Plant' in content


class FacilityTableLinkTests(ListTestCase):
    def test_city_and_county_link_to_their_region_pages(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        content = self.client.get(reverse('emissions:facility-list-table')).content.decode()
        assert f'href="{fresno.get_emissions_url()}"' in content
        assert f'href="{self.plant.city.get_emissions_url()}"' in content

    def test_a_county_in_the_scope_bar_goes_to_its_own_tab(self):
        # A county picked in the scope bar is that county's own Facilities tab (like OilGasPage), keeping the rest of the scope.
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        response = self.client.get(reverse('emissions:facility-list'), {'county': 'fresno', 'pollutant': 'rog'})
        assert response.status_code == 302
        assert response['Location'].startswith(fresno.get_emissions_tab_url('facilities'))
        assert 'pollutant=rog' in response['Location']


class PlaceSearchTests(ListTestCase):
    def search(self, q):
        response = self.client.get(reverse('api:v2:emissions:places'), {'q': q, 'type': 'region', 'year': 2024})
        assert response.status_code == 200
        return response.json()['results']

    def test_ab617_communities_are_found_and_labeled(self):
        community = make(Region.Type.AB617_COMMUNITY, 'Plantville', AROUND_PLANT)
        make(Region.Type.CITY, 'Plantville', AROUND_PLANT)
        results = self.search('plantv')
        assert ('Plantville', 'AB 617 community') in [(r['name'], r['detail']) for r in results]
        assert community.sqid in [r['id'] for r in results]
        # The id is a region page's: the facility list's old ?region= sends it to its Facilities tab.
        assert self.client.get(reverse('emissions:facility-list'), {'region': community.sqid}).status_code == 301

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
        # A city and the urban area of the same name are both offered, labeled.
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


class SectorsUnderFacilitiesTests(ListTestCase):
    def test_sectors_live_under_facilities(self):
        assert reverse('emissions:sector-list') == '/tools/emissions/facilities/sectors/'
        assert reverse('emissions:sector-detail', args=['glass']) == '/tools/emissions/facilities/sectors/glass/'

    def test_the_old_addresses_redirect_with_their_query(self):
        response = self.client.get('/tools/emissions/sectors/', {'sort': 'name'})
        assert response.status_code == 301
        assert response['Location'] == '/tools/emissions/facilities/sectors/?sort=name'
        response = self.client.get('/tools/emissions/sectors/glass/')
        assert response['Location'] == '/tools/emissions/facilities/sectors/glass/'

    def test_no_sectors_tab_and_facilities_is_active(self):
        for url in (reverse('emissions:sector-list'), reverse('emissions:sector-detail', args=['glass'])):
            content = self.client.get(url).content.decode()
            tabs = content.split('id="explorer-tabs"')[1].split('</ul>')[0]
            assert 'Sectors' not in tabs
            active = re.search(r'<li class="is-active"><a href="([^"]+)"', tabs)
            assert active.group(1).startswith(reverse('emissions:facility-list'))

    def test_the_switch_and_breadcrumbs(self):
        facilities = self.client.get(reverse('emissions:facility-list')).content.decode()
        sectors = self.client.get(reverse('emissions:sector-list')).content.decode()
        detail = self.client.get(reverse('emissions:sector-detail', args=['glass'])).content.decode()
        # One row on both: Summary | Table | Sectors, in the area tabs' style.
        for content in (facilities, sectors):
            row = content[content.index('subview-tabs'):content.index('</nav>', content.index('subview-tabs'))]
            assert row.index('>Summary<') < row.index('>Table<') < row.index('>Sectors<')
            assert 'href="/tools/emissions/facilities/table/"' in row and 'href="/tools/emissions/facilities/sectors/"' in row
        assert re.search(r'is-active"><a href="/tools/emissions/facilities/"[^>]*aria-current="page">.*Summary', facilities)
        assert re.search(r'is-active"><a href="/tools/emissions/facilities/sectors/"[^>]*aria-current="page">.*Sectors', sectors)
        assert '<a href="/tools/emissions/facilities/">Facilities</a>' in sectors
        assert '<a href="/tools/emissions/facilities/">Facilities</a>' in detail
        assert '<a href="/tools/emissions/facilities/sectors/">Sectors</a>' in detail


class ComplianceFilterTests(ListTestCase):
    def test_list_and_csv_follow_the_filter(self):
        from camp.apps.emissions.models import AirComplianceFacility
        AirComplianceFacility.objects.create(facility=self.plant, pgm_sys_id='CASJV00006019C0001', name='X', current_hpv='Unaddressed-Local', match_method='parsed')
        content = self.client.get(reverse('emissions:facility-list'), {'compliance': 'hpv'}).content.decode()
        assert 'Test Plant' in content and 'TEST CEMENT' not in content
        assert '<option value="hpv" selected>' in content
        body = self.client.get(reverse('emissions:facility-list'), {'compliance': 'any', 'format': 'csv'}).content.decode()
        assert 'TEST PLANT' in body and 'TEST CEMENT' not in body
        assert 'epa_tracked,hpv_status' in body.splitlines()[0]

    def test_the_map_follows_the_table_filters(self):
        from urllib.parse import parse_qs
        from camp.apps.emissions.models import AirComplianceFacility
        from camp.apps.emissions.tests.test_views import map_data
        AirComplianceFacility.objects.create(facility=self.plant, pgm_sys_id='CASJV00006019C0001', name='X', current_hpv='Unaddressed-Local', match_method='parsed')
        content = self.client.get(reverse('emissions:facility-list'), {'compliance': 'hpv', 'q': 'test'}).content.decode()
        query = parse_qs(map_data(content, 'query').replace('&amp;', '&'))
        assert query['compliance'] == ['hpv'] and query['q'] == ['test']
        # Unfiltered, the map's query carries neither.
        plain = parse_qs(map_data(self.client.get(reverse('emissions:facility-list')).content.decode(), 'query').replace('&amp;', '&'))
        assert 'compliance' not in plain and 'q' not in plain

    def test_the_geojson_takes_the_table_filters(self):
        from camp.apps.emissions.models import AirComplianceFacility
        AirComplianceFacility.objects.create(facility=self.plant, pgm_sys_id='CASJV00006019C0001', name='X', current_hpv='Unaddressed-Local', match_method='parsed')
        url = reverse('api:v2:emissions:geojson')
        def ids(**params):
            return {feature['properties']['name'] for feature in self.client.get(url, params).json()['features']}
        everything = ids()
        assert {'TEST PLANT', 'TEST CEMENT'} <= everything
        assert ids(compliance='hpv') == {'TEST PLANT'}
        assert ids(q='cement') == {'TEST CEMENT'}
        # An unknown compliance value is ignored, as the table ignores it.
        assert ids(compliance='nope') == everything


class FacilityListLayoutTests(ListTestCase):
    def test_a_page_of_25_with_its_count(self):
        content = self.client.get(reverse('emissions:facility-list-table')).content.decode()
        total = stats.facility_table(scope()).count()
        assert re.search(rf'Showing 1&ndash;{min(total, 25)} of {total} facilit', content)

    def test_no_trend_or_sectors_the_overview_has(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert 'Over time' not in content and 'Top sectors' not in content and 'sector-table' not in content

    def test_an_unranked_row_shows_a_dash(self):
        content = self.client.get(reverse('emissions:facility-list-table')).content.decode()
        assert '<td class="has-text-right cell-rank">None</td>' not in content

    def test_filters_sit_beside_the_map_with_sectors_a_to_z(self):
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        form = content[content.index('class="explorer-filters box"'):content.index('</form>')]
        # Every map's filters: the search, Search by location, then the tab's own.
        assert form.index('id="facility-q"') < form.index('Search by location') < form.index('id="facility-sector"') < form.index('id="facility-compliance"')
        assert 'form="facility-filters"' in form and 'id="facility-filters"' in form
        # The Summary: the filters beside the map, no table; the Table: the filters beside the table, no map.
        assert content.index('class="explorer-filters box"') < content.index('class="facility-map') and 'facility-table' not in content
        table = self.client.get(reverse('emissions:facility-list-table')).content.decode()
        assert table.index('class="explorer-filters box"') < table.index('facility-table') and 'class="facility-map' not in table
        # The county picker stays in the scope bar: it opens a county's own Facilities tab.
        assert 'data-scope="county"' in content
        # Scoped to the sector select itself: the facility list also carries
        # a compliance filter select now, whose own options aren't part of
        # this alphabetical-sectors check.
        sector_select = form[form.index('id="facility-sector"'):form.index('</select>', form.index('id="facility-sector"'))]
        labels = re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', sector_select)
        names = [label for value, label in labels]
        assert names[-1] == 'Other'
        assert names[:-1] == sorted(names[:-1])

    def test_the_summary_follows_the_filters(self):
        everything = self.client.get(reverse('emissions:facility-list')).content.decode()
        assert '<p class="heading">Facilities in' in everything and 'Matching facilities' not in everything
        assert 'card-header-title">Largest facilities' in everything and 'card-header-title">By sector' in everything
        # Narrowed: what matches, with no comparison to the unfiltered year; one sector needs no sector card.
        cement = self.client.get(reverse('emissions:facility-list'), {'q': 'cement'}).content.decode()
        assert re.search(r'Matching facilities in \d{4}</p><p class="title">1</p>', cement)
        card = cement[cement.index('card-header-title">Largest facilities'):cement.index('</table>', cement.index('card-header-title">Largest facilities'))]
        assert 'Test Cement' in card and 'Test Plant' not in card
        assert 'href="/tools/emissions/facilities/table/?q=cement"' in card
        glass = self.client.get(reverse('emissions:facility-list'), {'sector': self.plant.sector}).content.decode()
        assert 'card-header-title">By sector' not in glass

    def test_valley_header_and_map(self):
        # The top-level Facilities tab: its own header (what, where, then the
        # Summary | Table | Sectors row), no area tab row, a compact facilities map.
        content = self.client.get(reverse('emissions:facility-list')).content.decode()
        header = content[content.index('class="facilities-header"'):content.index('class="tab-stats"')]
        assert '<h1 class="mb-1">Facilities</h1>' in header and 'San Joaquin Valley' in header and 'NOx' in header
        assert 'subview-tabs' in header
        assert '<title>Facilities · San Joaquin Valley' in content
        assert '<li class="is-active"><a aria-current="page">Facilities</a></li>' in content
        assert 'class="facility-map' in content
        assert 'data-main-layer=""' in content or "data-main-layer=''" in content
