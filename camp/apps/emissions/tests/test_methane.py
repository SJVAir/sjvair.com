from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

import pytest

from camp.apps.emissions import methane
from camp.apps.emissions.importers import carbonmapper
from camp.apps.emissions.models import Facility, MethaneSource
from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, NEAR_BOTH, row
from camp.apps.emissions.tests.test_dairies import make_dairies

# Inside Fresno county, away from TEST PLANT and BIG DAIRY.
LONE = (-119.75, 36.76)


class MethaneTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.plant = Facility.objects.get(name='TEST PLANT')
        Facility.objects.filter(pk=self.plant.pk).update(point_source=Facility.PointSource.CENSUS)
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([
            row(name='near', lnglat=NEAR_BOTH),
            row(name='lone', lnglat=LONE, sector='6A', rate='30', unc='9'),
            row(name='og', lnglat=AT_GAS_STATION, sector='1B2', rate='500', unc='150'),
        ])
        self.near = MethaneSource.objects.get(source_name='near')


class CollectionTests(MethaneTestCase):
    def test_collection(self):
        body = methane.collection()
        assert body['type'] == 'FeatureCollection' and body['properties']['sources'] == 3
        assert body['properties']['imported'] is not None

    def test_features(self):
        by_name = {f['properties']['name']: f for f in methane.collection()['features']}
        near = by_name['near']
        assert near['id'] == self.near.sqid and near['geometry'] == {'type': 'Point', 'coordinates': [-119.786, 36.736]}
        p = near['properties']
        assert (p['group'], p['sector'], p['rate'], p['unc'], p['obs'], p['det']) == ('livestock', 'Dairies & livestock', 120.5, 40.2, 12, 5)
        assert p['rate_text'] == '120 ± 40 kg/h' and p['county'] == 'Fresno County'
        # Beside BIG DAIRY and TEST PLANT, but tied to neither (see MethaneSource).
        assert 'dairy' not in p and 'facility' not in p
        # No link out: Carbon Mapper's viewer doesn't open a source from a URL.
        assert 'viewer_url' not in p
        lone = by_name['lone']['properties']
        assert lone['group'] == 'waste'

    def test_collection_is_cached_under_the_generation(self):
        assert methane.collection()['properties']['sources'] == 3
        MethaneSource.objects.filter(source_name='lone').delete()
        assert methane.collection()['properties']['sources'] == 3
        methane.clear_caches()
        assert methane.collection()['properties']['sources'] == 2


class AreaRowsTests(MethaneTestCase):
    def test_sources_by_carbon_mappers_sector(self):
        from camp.apps.emissions import areas
        rows = methane.area_rows(areas.ValleyArea(), groups=[MethaneSource.Group.OIL_GAS])
        assert [(r['source'].source_name, r['county'].slug) for r in rows] == [('og', 'kern')]
        # Never tied to a facility or dairy: a source is its place and Carbon Mapper's sector.
        assert 'facility' not in rows[0] and 'dairy' not in rows[0]

    def test_the_oil_gas_tab_links_the_methane_tab(self):
        from camp.apps.regions.models import Region
        from camp.apps.emissions.tests.test_wells import make_well
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        make_well('0402900001', (-119.02, 35.37), kern)
        content = self.client.get(kern.get_emissions_tab_url('oil-gas')).content.decode()
        assert f'href="{kern.get_emissions_tab_url("methane")}?sector=oil-gas">1 oil &amp; gas methane source seen here' in content
        valley = self.client.get(reverse('emissions:oil-gas')).content.decode()
        assert 'href="/tools/emissions/methane/?sector=oil-gas">1 oil &amp; gas methane source seen in the covered counties' in valley


class ViewTests(MethaneTestCase):
    def test_the_old_same_origin_route_is_gone(self):
        # Moved to /api/2.0/emissions/methane/geojson/ (camp/api/v2/emissions/tests.py
        # pins the new route and its attribution/license).
        with pytest.raises(NoReverseMatch):
            reverse('emissions:methane-geojson')
        assert self.client.get('/tools/emissions/methane/geojson/').status_code == 404


class OverlayConfigTests(MethaneTestCase):
    def test_methane_overlay_helper(self):
        from camp.apps.emissions import views
        assert views.methane_overlay({}) == {'on': False, 'default': False, 'params': {}}
        assert views.methane_overlay({'methane': '1'}) == {'on': True, 'default': False, 'params': {}}
        assert views.methane_overlay({'methane': '0'}, default=True) == {'on': False, 'default': True, 'params': {}}
        assert views.methane_overlay({'methane': 'x'}) == {'on': False, 'default': False, 'params': {}}
        # The Methane pages narrow it to the table's sector groups; elsewhere they're ignored.
        assert views.methane_overlay({'sector': 'oil-gas,waste'}, filtered=True)['params'] == {'sector': 'oil-gas,waste'}
        assert views.methane_overlay({'sector': 'oil-gas'})['params'] == {}
        MethaneSource.objects.all().delete()
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.filter(source='carbon-mapper').delete()
        assert views.methane_overlay({'methane': '1'}) is None

    def test_every_map_offers_the_overlay(self):
        """On for the main map and Overviews (every location) and the dairy and oil & gas maps; the facility-only maps have none."""
        from camp.apps.emissions.tests.test_views import map_data
        from camp.apps.emissions.tests.test_wells import make_well
        region = self.plant.county
        make_well('0401900001', self.plant.point, region)  # so the Oil & gas tab has a map
        defaults = {
            reverse('emissions:map'): '1',
            region.get_emissions_url(): '1',
            region.get_emissions_tab_url('oil-gas'): '1',
            region.get_emissions_dairies_url(): '1',
            reverse('emissions:dairy-list'): '1',
            reverse('emissions:oil-gas'): '1',
        }
        for url, on in defaults.items():
            content = self.client.get(url, {'year': 2023}).content.decode()
            # An area page's limited to its area (?region= / ?lat=&lng=&radius=).
            assert map_data(content, 'methane-url').split('?')[0] == reverse('api:v2:emissions:methane-geojson'), url
            assert map_data(content, 'methane-plumes-url') == reverse('api:v2:emissions:methane-plumes', args=['__id__']).replace('__id__', '{id}'), url
            assert map_data(content, 'methane') == on, url
            assert map_data(content, 'methane-default') == on, url
        for url in (self.plant.get_absolute_url(), region.get_emissions_tab_url('facilities'), reverse('emissions:sector-detail', args=['oil-gas'])):
            assert map_data(self.client.get(url, {'year': 2023}).content.decode(), 'methane-url') == '', url
        content = self.client.get(reverse('emissions:map'), {'methane': '0'}).content.decode()
        assert map_data(content, 'methane') == ''
        content = self.client.get(reverse('emissions:dairy-list'), {'methane': '0'}).content.decode()
        assert map_data(content, 'methane') == ''

    def test_nothing_offered_before_an_import(self):
        from camp.apps.emissions.models import SourceImport
        from camp.apps.emissions.tests.test_views import map_data
        MethaneSource.objects.all().delete()
        SourceImport.objects.filter(source='carbon-mapper').delete()
        methane.clear_caches()
        content = self.client.get(reverse('emissions:map'), {'methane': '1'}).content.decode()
        assert map_data(content, 'methane-url') == ''

    def test_about_has_the_methane_section(self):
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="methane">Methane</h2>' in content
        assert 'Data by Carbon Mapper®' in content and 'https://carbonmapper.org/terms' in content
        assert 'not an annual total' in content and 'Methane is a climate pollutant, not a direct local toxic' in content


class MethaneTabTests(MethaneTestCase):
    """The Methane tab (views.MethanePage, RegionMethane, NearMeMethane): Summary and Table under the sector filter."""

    def get(self, url, params=None):
        response = self.client.get(url, params or {})
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def test_the_valley_summary(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.get(reverse('emissions:methane'))
        # The explorer's own tab, the Summary | Table switch, the stats, a methane-only map and the cards.
        assert 'is-active"><a href="/tools/emissions/methane/' in content
        assert 'subview-tabs' in content and 'href="/tools/emissions/methane/table/"' in content
        assert '<p class="heading">Methane sources</p><p class="title">3</p>' in content
        assert map_data(content, 'main-layer') == 'none' and map_data(content, 'methane') == '1'
        assert 'card-header-title">Sources by sector' in content and 'card-header-title">Highest estimated rates' in content
        assert 'methane-table' not in content
        # Every sector ticked; the filter starts at Search by location (a source has no name to search).
        assert content.count('type="checkbox" name="sector"') == 4 and 'id="methane-q"' not in content

    def test_the_sector_filter_narrows_the_map_and_the_table(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.get(reverse('emissions:methane'), {'sector': 'oil-gas'})
        assert '<p class="heading">Methane sources</p><p class="title">1</p>' in content
        assert 'sector=oil-gas' in map_data(content, 'methane-url')
        api = self.client.get(reverse('api:v2:emissions:methane-geojson'), {'sector': 'oil-gas,waste'}).json()
        assert sorted(feature['properties']['name'] for feature in api['features']) == ['lone', 'og']
        table = self.get(reverse('emissions:methane-table'), {'sector': ['livestock', 'waste']})
        rows = table[table.index('methane-table'):table.index('</table>', table.index('methane-table'))]
        assert rows.count('<tr>') == 3  # header + two Fresno sources
        assert 'Waste' in rows and 'Oil &amp; gas' not in rows

    def test_the_table(self):
        table = self.get(reverse('emissions:methane-table'))
        rows = table[table.index('methane-table'):table.index('</table>', table.index('methane-table'))]
        # The highest rate first; the Valley's table has a County column; no map and no CSV (Carbon Mapper's terms).
        assert rows.index('500 ± 150 kg/h') < rows.index('120 ± 40 kg/h') < rows.index('30 ± 9 kg/h')
        assert '>County <span class="icon' in rows and 'map-canvas' not in table
        assert 'format=csv' not in table and 'Showing 1&ndash;3 of 3 sources' in table
        by_rate = self.get(reverse('emissions:methane-table'), {'sort': 'rate'})
        assert by_rate.index('30 ± 9 kg/h') < by_rate.index('500 ± 150 kg/h')

    def test_an_area_tab(self):
        from camp.apps.regions.models import Region
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        url = fresno.get_emissions_tab_url('methane')
        content = self.get(url)
        # In the area's tab row, current; its own sources only.
        assert f'href="{url}' in content and '<p class="heading">Methane sources</p><p class="title">2</p>' in content
        table = self.get(url + 'table/')
        rows = table[table.index('methane-table'):table.index('</table>', table.index('methane-table'))]
        # A county's own table drops the County column.
        assert rows.count('<tr>') == 3 and '>County <span class="icon' not in rows
        assert 'Methane' in self.get(fresno.get_emissions_url())

    def test_a_county_in_the_scope_bar_goes_to_its_own_tab(self):
        from camp.apps.regions.models import Region
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        response = self.client.get(reverse('emissions:methane-table'), {'county': 'kern'})
        assert response.status_code == 302 and response['Location'].startswith(kern.get_emissions_tab_url('methane') + 'table/')

    def test_before_any_import(self):
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.filter(source='carbon-mapper').delete()
        cache.clear()
        assert 'No methane data has been imported yet.' in self.get(reverse('emissions:methane'))
