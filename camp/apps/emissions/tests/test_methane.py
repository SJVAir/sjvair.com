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
        assert p['viewer_url'] == 'https://data.carbonmapper.org/#36.73600,-119.78600'
        lone = by_name['lone']['properties']
        assert lone['group'] == 'waste'

    def test_collection_is_cached_under_the_generation(self):
        assert methane.collection()['properties']['sources'] == 3
        MethaneSource.objects.filter(source_name='lone').delete()
        assert methane.collection()['properties']['sources'] == 3
        methane.clear_caches()
        assert methane.collection()['properties']['sources'] == 2


class OilGasListTests(MethaneTestCase):
    def test_oil_gas_sources_by_carbon_mappers_sector(self):
        rows = methane.oil_gas_sources()
        assert [(r['source'].source_name, r['county'].slug) for r in rows] == [('og', 'kern')]
        assert 'facility' not in rows[0]


class ViewTests(MethaneTestCase):
    def test_the_old_same_origin_route_is_gone(self):
        # Moved to /api/2.0/emissions/methane/geojson/ (camp/api/v2/emissions/tests.py
        # pins the new route and its attribution/licence).
        with pytest.raises(NoReverseMatch):
            reverse('emissions:methane-geojson')
        assert self.client.get('/tools/emissions/methane/geojson/').status_code == 404


class OverlayConfigTests(MethaneTestCase):
    def test_methane_overlay_helper(self):
        from camp.apps.emissions import views
        assert views.methane_overlay({}) == {'on': False, 'default': False}
        assert views.methane_overlay({'methane': '1'}) == {'on': True, 'default': False}
        assert views.methane_overlay({'methane': '0'}, default=True) == {'on': False, 'default': True}
        assert views.methane_overlay({'methane': 'x'}) == {'on': False, 'default': False}
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
