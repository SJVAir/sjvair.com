import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import views
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
        assert views.wells_overlay({}) == {'on': False, 'default': False}
        assert views.wells_overlay({}, default=True) == {'on': True, 'default': True}
        assert views.wells_overlay({'wells': '1'}) == {'on': True, 'default': False}
        assert views.wells_overlay({'wells': '0'}, default=True) == {'on': False, 'default': True}
        assert views.wells_overlay({'wells': 'x'}, default=True)['on'] is True

    def test_off_by_default_on_by_request(self):
        for url in (reverse('emissions:map'), self.fresno.get_emissions_url(), reverse('emissions:near-me') + '?lat=36.737&lng=-119.787'):
            content = self.get(url)
            assert map_data(content, 'wells') == '' and map_data(content, 'wells-default') == '', url
            assert map_data(content, 'wells-url') == reverse('api:v2:emissions:wells-geojson'), url
            assert '{id}' in map_data(content, 'well-url')
        content = self.get(reverse('emissions:map'), {'wells': '1'})
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == ''

    def test_on_by_default_on_the_oil_gas_tab_and_sector(self):
        oil_gas = self.kern.get_emissions_tab_url('oil-gas')
        content = self.get(oil_gas)
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == '1'
        assert map_data(self.get(oil_gas, {'wells': '0'}), 'wells') == ''
        # Off on Kern's Overview: 66,000 wells are too many to load there by default.
        content = self.get(self.kern.get_emissions_url())
        assert map_data(content, 'wells') == '' and map_data(content, 'wells-url')
        content = self.get(reverse('emissions:sector-detail', args=['oil-gas']))
        assert map_data(content, 'wells') == '1'
        assert map_data(self.get(reverse('emissions:sector-detail', args=['glass'])), 'wells') == ''

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
        assert '<strong>1</strong> school or child-care center here has an active or idle well within 3,200 ft' in block
        assert re.search(r'PLANT ELEMENTARY</td><td class="cell-meta">Public school</td><td[^>]*data-unit="wells">2</td>', block)
        assert 'Oil &amp; gas facilities reported' not in block  # the Kern sentence is Kern's
        assert 'href="/tools/emissions/about/#oil-gas"' in block

    def test_the_snapshot_caveat_names_the_year(self):
        self.add_wells()
        latest = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2024'})
        block = latest[latest.index('id="wells"'):]
        assert '<strong>Current wells' in block and 'It has no history by year' in block
        assert "not 2024's" not in block
        past = self.get(self.fresno.get_emissions_tab_url('oil-gas'), {'year': '2023'})
        block = past[past.index('id="wells"'):]
        assert "<strong>These are today's wells, not 2023's.</strong>" in block.replace('&#x27;', "'")
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

    def test_sector_page_callout(self):
        self.add_kern_oil_gas()
        content = self.get(reverse('emissions:sector-detail', args=['oil-gas']), {'year': '2024'})
        assert "80% of Kern" in content and 'permit groupings that can span a whole oil field' in content
        assert 'id="wells"' not in content
        assert '80% of Kern' not in self.get(reverse('emissions:sector-detail', args=['glass']), {'year': '2024'})


class FacilityNoteTests(WellsPagesTestCase):
    def test_oil_gas_note_replaces_the_schools_card(self):
        location('PLANT ELEMENTARY', north_of(self.plant.point, 500))
        Facility.objects.filter(pk=self.plant.pk).update(sector='oil-gas', point_source='census')
        content = self.get(self.plant.get_absolute_url())
        assert 'This is a district permit grouping that can span a whole oil field. Its map point is the operator&#x27;s address, not a well.' in content \
            or "Its map point is the operator's address, not a well." in content
        assert 'Schools and child care nearby' not in content
        Facility.objects.filter(pk=self.plant.pk).update(sector='glass')
        content = self.get(self.plant.get_absolute_url())
        assert 'district permit grouping' not in content and 'Schools and child care nearby' in content


class AboutTests(WellsPagesTestCase):
    def test_about_and_integrations(self):
        content = self.get(reverse('emissions:about'))
        assert '<h2 id="oil-gas">Oil and gas</h2>' in content
        assert "Well counts are CalGEM's regulatory records, not emissions." in content or 'Well counts are CalGEM&#x27;s regulatory records' in content
        assert 'No well data has been imported yet.' in content
        assert 'WellSTAR' in self.get('/about/integrations/')
