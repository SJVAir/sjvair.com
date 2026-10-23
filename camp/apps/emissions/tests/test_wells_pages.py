import re

from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import areas, views, wells
from camp.apps.emissions.models import EmissionsRecord, Facility, ToxicEmission, ToxicPollutant
from camp.apps.emissions.tests.test_areas_pages import map_data
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.emissions.tests.test_wells import location, make_well, north_of
from camp.apps.regions.models import Region


class WellsPagesTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')

    def get(self, url, params=None, status=200):
        response = self.client.get(url, params or {})
        assert response.status_code == status, response.status_code
        return response.content.decode()

    def add_wells(self):
        make_well('0402900001', IN_KERN, self.kern)
        make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), self.kern, status='Idle', hpz='Verified HPZ')
        make_well('0401900004', NEAR_PLANT, self.fresno)
        make_well('0401900010', north_of(self.plant.point, 3000), self.fresno)
        location('PLANT ELEMENTARY', self.plant.point)

    def add_kern_oil_gas(self):
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=77, name='HEAVY OIL WESTERN',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.8')
        ToxicEmission.objects.create(facility=rig, year=2024, pollutant=ToxicPollutant.objects.get(carb_id='71432'), lbs='3')
        return rig


class OverlayConfigTests(WellsPagesTestCase):
    def test_wells_overlay_helper(self):
        assert views.wells_overlay({}) == {'on': False, 'default': False, 'params': {}}
        assert views.wells_overlay({}, default=True) == {'on': True, 'default': True, 'params': {}}
        assert views.wells_overlay({'wells': '1'}) == {'on': True, 'default': False, 'params': {}}
        assert views.wells_overlay({'wells': '0'}, default=True) == {'on': False, 'default': True, 'params': {}}
        assert views.wells_overlay({'wells': 'x'}, default=True)['on'] is True
        # The Oil & gas pages narrow it to the table's filters; elsewhere they're ignored.
        get = {'status': 'Idle', 'hpz': '1', 'q': ' ', 'sort': 'api'}
        assert views.wells_overlay(get, filtered=True)['params'] == {'status': 'Idle', 'hpz': '1'}
        assert views.wells_overlay(get)['params'] == {}
        assert wells.table_filters(QueryDict('status=New&status=Active'))['status'] == ['Active', 'New']
        assert wells.table_filters(QueryDict('status=Active&status=Idle&status=New'))['status'] is None

    def test_off_by_default_on_by_request(self):
        for url in (self.fresno.get_emissions_url(), reverse('emissions:near-me') + '?lat=36.737&lng=-119.787'):
            content = self.get(url)
            assert map_data(content, 'wells') == '' and map_data(content, 'wells-default') == '', url
            assert map_data(content, 'wells-url').split('?')[0] == reverse('api:v2:emissions:wells-geojson'), url
            assert '{id}' in map_data(content, 'well-url')
        content = self.get(self.fresno.get_emissions_url(), {'wells': '1'})
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == ''

    def test_on_by_default_on_the_main_map(self):
        # The Valley map's legend layers all start on, the wells included; ?wells=0 turns them off.
        content = self.get(reverse('emissions:map'))
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == '1'
        assert map_data(self.get(reverse('emissions:map'), {'wells': '0'}), 'wells') == ''

    def test_on_by_default_on_the_oil_gas_tabs(self):
        self.add_wells()
        oil_gas = self.kern.get_emissions_tab_url('oil-gas')
        content = self.get(oil_gas)
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == '1'
        assert map_data(self.get(oil_gas, {'wells': '0'}), 'wells') == ''
        # Off on Kern's Overview: 66,000 wells are too many to load there by default.
        content = self.get(self.kern.get_emissions_url())
        assert map_data(content, 'wells') == '' and map_data(content, 'wells-url')
        # On for the Valley's Oil & gas tab; off on the oil & gas sector page, like the Facilities list.
        assert map_data(self.get(reverse('emissions:oil-gas')), 'wells') == '1'
        assert map_data(self.get(reverse('emissions:sector-detail', args=['oil-gas'])), 'wells') == ''

    def test_a_facilitys_own_map_has_no_overlay(self):
        content = self.get(self.plant.get_absolute_url())
        assert map_data(content, 'wells-url') == '' and map_data(content, 'wells') == ''


class WellsBlockTests(WellsPagesTestCase):
    def test_no_tab_without_wells(self):
        content = self.get(self.fresno.get_emissions_url())
        assert self.fresno.get_emissions_tab_url('oil-gas') not in content
        content = self.get(self.fresno.get_emissions_tab_url('oil-gas'))
        assert 'id="wells"' not in content and 'No active, idle or new oil or gas wells here.' in content

    def test_region_block(self):
        self.add_wells()
        assert f'href="{self.fresno.get_emissions_tab_url("oil-gas")}' in self.get(self.fresno.get_emissions_url())
        content = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2024'})
        block = content[content.index('id="wells"'):]
        assert '2 active · 0 idle · 0 in a verified health-protection zone (3,200 ft of homes or schools)' in block
        # A card: how many, the most wells first, View all on the area's Schools tab narrowed to sites near a well.
        card = block[block.index('id="schools-near-wells"'):]
        assert '<strong>1</strong> has an active or idle well within 3,200 ft.' in card
        # The name cell is the Schools tab's own (school-name-cell.html): the school's name, then its type/district line.
        assert re.search(r'PLANT ELEMENTARY<span class="school-kind">Public school[^<]*</span></td><td class="has-text-right">2</td>', card)
        assert re.search(rf'href="{self.fresno.get_emissions_tab_url("schools")}\?[^"]*near=wells">View all', card)
        near = self.get(self.fresno.get_emissions_tab_url('schools'), {'year': '2024', 'near': 'wells'})
        assert '<option value="wells" selected>' in near and 'PLANT ELEMENTARY' in near
        assert 'Oil &amp; gas facilities reported' not in block  # the Kern sentence is Kern's
        assert 'href="/tools/emissions/about/#oil-gas"' in block

    def test_the_type_filter_groups_calgems_types(self):
        from django.db.models import Q
        self.add_wells()
        # Kern's two from add_wells: one Oil & Gas (OG), one Cyclic Steam (SC); an observation well besides.
        from camp.apps.emissions.models import Well
        Well.objects.filter(api='0402900001').update(well_type='OG')
        Well.objects.filter(api='0402900002').update(well_type='SC', well_type_label='Cyclic Steam')
        make_well('0402900003', (-119.02, 35.371), self.kern, well_type='OB', well_type_label='Observation')
        kern = Well.objects.filter(county=self.kern)
        assert set(kern.filter(wells.type_q(['producing'])).values_list('api', flat=True)) == {'0402900001'}
        assert set(kern.filter(wells.type_q(['injecting'])).values_list('api', flat=True)) == {'0402900002'}
        # Other is everything the first three don't list.
        assert set(kern.filter(wells.type_q(['other'])).values_list('api', flat=True)) == {'0402900003'}
        assert wells.table_filters(QueryDict('type=other&type=producing'))['types'] == ['producing', 'other']
        assert wells.table_filters(QueryDict('type=' + '&type='.join(wells.TYPE_VALUES)))['types'] is None
        url = self.kern.get_emissions_tab_url('oil-gas')
        summary = self.get(url, {'type': 'injecting'})
        assert '<p class="heading">Idle wells</p><p class="title">1</p>' in summary and '<p class="heading">Active wells</p><p class="title">0</p>' in summary
        assert 'type=injecting' in map_data(summary, 'wells-url').replace('&amp;', '&')
        assert summary.count('type="checkbox" name="type"') == 4 and 'name="type" value="producing">' in summary
        table = self.get(url + 'table/', {'type': ['producing', 'other']})
        assert 'Showing 1&ndash;2 of 2 wells' in table
        api = self.client.get(reverse('api:v2:emissions:wells-geojson'), {'region': self.kern.sqid, 'type': 'injecting'}).json()
        assert len(api['wells']) == 1

    def test_the_snapshot_caveat_names_the_year(self):
        self.add_wells()
        latest = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2024'})
        block = latest[latest.index('id="wells"'):]
        assert '<strong>Current wells' in block and 'It has no history by year' in block
        assert "not 2024's" not in block
        past = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2023'})
        block = past[past.index('id="wells"'):]
        assert "<strong>These are current wells, not 2023's.</strong>" in block.replace('&#x27;', "'")
        assert 'The emissions figures on this page are for 2023.' in block

    def test_kern_block_has_the_callout(self):
        self.add_wells()
        self.add_kern_oil_gas()
        content = self.get(self.kern.get_emissions_tab_url('oil-gas'), {'year': '2024'})
        block = content[content.index('id="wells"'):]
        assert '1 active · 1 idle · 1 in a verified health-protection zone' in block
        assert "Oil &amp; gas facilities reported 80% of Kern&#x27;s permitted-facility ROG and 86% of its benzene in 2024" in block \
            or "Oil &amp; gas facilities reported 80% of Kern's permitted-facility ROG and 86% of its benzene in 2024" in block
        assert 'No school or child-care center here has a well within 3,200 ft.' in block

    def test_near_me_block(self):
        self.add_wells()
        content = self.get(reverse('emissions:near-me-oil-gas'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2024'})
        assert 'id="wells"' in content and '2 active' in content

    def test_the_callout_moved_from_the_sector_page_to_the_oil_gas_tab(self):
        self.add_kern_oil_gas()
        self.add_wells()
        content = self.get(reverse('emissions:oil-gas'), {'year': '2024'})
        assert "80% of Kern" in content
        sector = self.get(reverse('emissions:sector-detail', args=['oil-gas']), {'year': '2024'})
        assert '80% of Kern' not in sector and 'id="wells"' not in sector
        assert 'permit groupings placed at an operator' in sector and f'href="{reverse("emissions:oil-gas")}' in sector
        assert 'Wells, drilling and methane' not in self.get(reverse('emissions:sector-detail', args=['glass']), {'year': '2024'})


class OilGasTabTests(WellsPagesTestCase):
    """The Oil & gas tab's table, filters, CSV and chart (area-oil-gas.html)."""

    def test_the_wells_table_filters_and_csv(self):
        self.add_wells()
        url = self.fresno.get_emissions_tab_url('oil-gas') + 'table/'
        content = self.get(url, {'year': '2024'})
        table = content[content.index('well-table'):content.index('</table>', content.index('well-table'))]
        assert table.count('<tr>') == 3  # header + Fresno's two wells
        # The Table: the filters beside it, no map; the count and CSV over it; each well's CalGEM links in the last column.
        assert content.index('class="explorer-filters box"') < content.index('well-table') and 'map-canvas' not in content
        assert 'class="cell-links"' in table and 'Well/Well/Detail?api=' in table and 'target="_blank"' in table
        assert 'Showing 1&ndash;2 of 2 wells' in content and 'Download CSV' in content
        assert 'Top operators' not in content and 'Drilled by year' not in content
        idle = self.get(url, {'year': '2024', 'status': 'Idle'})
        idle_table = idle[idle.index('well-table'):idle.index('</table>', idle.index('well-table'))]
        assert 'No wells match.' in idle_table
        # Status is a set of checkboxes, all ticked until one is left out; any mix narrows the table.
        assert content.count('type="checkbox" name="status"') == 3 and content.count('name="status" value="Active" checked') == 1
        assert 'name="status" value="Idle" checked' in idle and 'name="status" value="Active">' in idle
        mixed = self.get(url, {'year': '2024', 'status': ['Idle', 'New']})
        assert 'No wells match.' in mixed and 'name="status" value="New" checked' in mixed and 'name="status" value="Active">' in mixed
        both = self.get(url, {'year': '2024', 'status': ['Active', 'Idle']})
        assert 'Showing 1&ndash;2 of 2 wells' in both
        response = self.client.get(url, {'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        rows = response.content.decode().strip().splitlines()
        assert rows[0].startswith('api,lease,well_number,status') and len(rows) == 3

    def test_summary_and_table_share_the_filters(self):
        self.add_wells()
        summary_url = self.kern.get_emissions_tab_url('oil-gas')
        summary = self.get(summary_url, {'status': 'Idle', 'page': '2'})
        # The Summary: the map and what sums it up, no table; the switch to the Table keeps the filters, not the page.
        assert 'map-canvas' in summary and 'well-table' not in summary and 'Download CSV' not in summary
        switch = summary[summary.index('subview-toggle'):summary.index('</nav>', summary.index('subview-toggle'))]
        assert f'href="{summary_url}table/?status=Idle"' in switch and 'aria-current="page"><span class="icon is-small"><span class="fa-duotone fa-fw fa-chart-pie"' in switch
        # Its stats and cards follow the filters: one idle well of Kern's two.
        stats = summary[summary.index('wells-line'):summary.index('</div>\n    \n', summary.index('wells-line'))]
        assert '<p class="heading">Idle wells</p><p class="title">1</p>' in stats and '<p class="heading">Active wells</p><p class="title">0</p>' in stats
        assert 'No wells match these filters.' in self.get(summary_url, {'operator': 'NOBODY'})
        table = self.get(summary_url + 'table/', {'status': 'Idle'})
        assert f'href="{summary_url}?status=Idle"' in table and 'Search by location' not in table
        # Clearing the filters stays on the Table.
        clear = table[table.index('filters-clear'):table.index('</p>', table.index('filters-clear'))]
        assert f'href="{summary_url}table/' in clear

    def test_the_map_follows_the_table_filters(self):
        self.add_wells()
        content = self.get(self.kern.get_emissions_tab_url('oil-gas'), {'status': 'Idle'})
        url = map_data(content, 'wells-url').replace('&amp;', '&')
        assert 'status=Idle' in url and f'region={self.kern.sqid}' in url
        def api(**params):
            return [row[0] for row in self.client.get(reverse('api:v2:emissions:wells-geojson'), params).json()['wells']]
        everything = api(region=self.kern.sqid)
        assert len(everything) == 2
        # Cached per filter: the unfiltered response above doesn't answer the filtered one.
        assert len(api(region=self.kern.sqid, status='Idle')) == 1
        assert len(api(region=self.kern.sqid, hpz='1')) == 1
        assert api(region=self.kern.sqid, status='nope') == everything
        # Several statuses travel comma-joined, as the map's URL carries them; all three is no filter.
        assert len(api(region=self.kern.sqid, status='Idle,New')) == 1
        assert api(region=self.kern.sqid, status='Active,Idle,New') == everything
        mixed = self.get(self.kern.get_emissions_tab_url('oil-gas'), {'status': ['Active', 'Idle']})
        assert 'status=Active%2CIdle' in map_data(mixed, 'wells-url').replace('&amp;', '&')
        # Free text (an operator with spaces) is answered uncached, not keyed.
        assert len(api(region=self.kern.sqid, operator='TEST OIL LLC')) == 2
        assert api(region=self.kern.sqid, operator='NOBODY AT ALL') == []

    def test_top_operators_and_fields(self):
        self.add_wells()
        make_well('0401900011', NEAR_PLANT, self.fresno, operator_name='OTHER OIL CO', field_name='Other Field')
        content = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2024'})
        # On the Summary, under the filters; each a link narrowing the page to it, the rest of the query kept.
        card = content[content.index('Top operators'):content.index('</table>', content.index('Top operators'))]
        # The most wells first, each linking the tab's table filtered to it.
        assert card.index('TEST OIL LLC') < card.index('OTHER OIL CO')
        assert 'oil-gas/?year=2024&amp;operator=OTHER+OIL+CO"' in card
        assert '<td class="has-text-right">2</td>' in card
        fields = content[content.index('Top oil fields'):content.index('</table>', content.index('Top oil fields'))]
        assert 'field=Other+Field' in fields

    def test_leaders(self):
        self.add_wells()
        leaders = wells.leaders(areas.RegionArea(self.kern))
        assert leaders == {'operators': [{'label': 'TEST OIL LLC', 'count': 2}], 'fields': [{'label': 'Test Field', 'count': 2}]}

    def test_the_tab_without_wells_says_so(self):
        content = self.get(self.fresno.get_emissions_tab_url('oil-gas'))
        assert 'No active, idle or new oil or gas wells here.' in content and 'well-table' not in content


class FacilityNoteTests(WellsPagesTestCase):
    def test_oil_gas_note_replaces_the_schools_card(self):
        location('PLANT ELEMENTARY', north_of(self.plant.point, 500))
        Facility.objects.filter(pk=self.plant.pk).update(sector='oil-gas', point_source='census')
        content = self.get(self.plant.get_absolute_url())
        assert 'its map point is the operator&#x27;s address, not a well' in content \
            or "its map point is the operator's address, not a well" in content
        assert 'Schools &amp; child care within ¼ mile' not in content
        Facility.objects.filter(pk=self.plant.pk).update(sector='glass')
        content = self.get(self.plant.get_absolute_url())
        assert 'district permit grouping' not in content and 'Schools &amp; child care within ¼ mile' in content


class AboutTests(WellsPagesTestCase):
    def test_about_and_integrations(self):
        content = self.get(reverse('emissions:about'))
        assert '<section class="about-section" id="oil-gas">' in content
        assert "Well counts are CalGEM's regulatory records, not emissions." in content or 'Well counts are CalGEM&#x27;s regulatory records' in content
        assert 'No well data has been imported yet.' in content
        assert 'WellSTAR' in self.get('/about/integrations/')


class ValleyOilGasTabTests(WellsPagesTestCase):
    """The top-level Oil & gas tab (views.OilGasPage): the area tab for the whole Valley."""

    def test_the_valley_tab(self):
        self.add_wells()
        url = reverse('emissions:oil-gas')
        content = self.get(url + 'table/', {'year': '2024'})
        # Every covered county's wells, the explorer tab marked current, and the scope bar's
        # county picker into an area's own tab.
        table = content[content.index('well-table'):content.index('</table>', content.index('well-table'))]
        assert table.count('<tr>') == 5  # header + all four wells
        assert 'class="is-active"><a href="/tools/emissions/oil-gas/' in content.replace("is-active\"", 'is-active"')
        assert 'data-scope="county"' in content
        box = content[content.index('class="explorer-filters box"'):content.index('</form>', content.index('class="explorer-filters box"'))]
        assert box.index('id="well-q"') < box.index('Search by location') < box.index('name="status"')
        # Search by location lands on a place's Table from here.
        assert self.kern.get_emissions_tab_url('oil-gas') + 'table/' in content
        summary = self.get(url, {'year': '2024'})
        assert 'Top operators' in summary and 'Schools and child care near wells' in summary and 'well-table' not in summary
        response = self.client.get(url, {'format': 'csv'})
        assert response['Content-Type'] == 'text/csv' and len(response.content.decode().strip().splitlines()) == 5

    def test_a_county_in_the_scope_bar_goes_to_its_own_tab(self):
        response = self.client.get(reverse('emissions:oil-gas'), {'county': 'kern', 'year': '2024'})
        assert response.status_code == 302 and response['Location'].startswith(self.kern.get_emissions_tab_url('oil-gas'))

    def test_leader_links_stay_on_the_valley_tab(self):
        self.add_wells()
        content = self.get(reverse('emissions:oil-gas'))
        assert 'href="/tools/emissions/oil-gas/?operator=TEST+OIL+LLC"' in content


class TabLayerTests(WellsPagesTestCase):
    """Each dataset page maps its dataset and what goes with it (views.area_tab_layers)."""

    def test_each_tab_maps_its_own_layers(self):
        self.add_wells()
        oil_gas = self.get(self.kern.get_emissions_tab_url('oil-gas'))
        # Oil & gas has an Areas view of its own: the wells' counts per area.
        assert map_data(oil_gas, 'main-layer') == 'none' and map_data(oil_gas, 'wells-url') and map_data(oil_gas, 'areas') == '1'
        assert map_data(oil_gas, 'areas-kind') == 'wells' and map_data(oil_gas, 'areas-url') == reverse('api:v2:emissions:wells-areas')
        assert 'data-measure="hpz_share"' in oil_gas and 'map-toolbar-label">Wells<' in oil_gas
        facilities = self.get(self.kern.get_emissions_tab_url('facilities'))
        assert map_data(facilities, 'main-layer') == '' and map_data(facilities, 'wells-url') == '' and map_data(facilities, 'areas') == '1'
        overview = self.get(self.kern.get_emissions_url())
        assert map_data(overview, 'wells-url') and map_data(overview, 'wells') == '' and map_data(overview, 'areas') == '1'
        valley = self.get(reverse('emissions:oil-gas'))
        assert map_data(valley, 'main-layer') == 'none'


class DistrictLineTests(WellsPagesTestCase):
    def test_district_lines_only_on_valley_wide_maps(self):
        assert map_data(self.get(reverse('emissions:map')), 'districts-url') == reverse('api:v2:emissions:districts')
        assert map_data(self.get(reverse('emissions:sector-detail', args=['glass'])), 'districts-url')
        for url in (self.kern.get_emissions_url(), self.kern.get_emissions_tab_url('facilities'), self.plant.get_absolute_url(),
                    reverse('emissions:near-me') + '?lat=36.737&lng=-119.787'):
            assert map_data(self.get(url), 'districts-url') == '', url


class ClusterSettingTests(TestCase):
    """The Tweaks menu's Clusters select (the shared ?cluster= setting): only on a map with wells."""
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_the_select_shows_where_there_are_wells(self):
        cache.clear()
        make_well('0402900001', IN_KERN, Region.objects.get(type=Region.Type.COUNTY, slug='kern'))
        assert 'name="cluster"' in self.client.get(reverse('emissions:oil-gas')).content.decode()
        assert 'name="cluster"' not in self.client.get(reverse('emissions:facility-list')).content.decode()

