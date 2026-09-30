import re

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions.models import EmissionsRecord, Facility, ToxicEmission
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.regions.models import Region


class FacilityHeaderTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def detail(self, name):
        return self.client.get(Facility.objects.get(name=name).get_absolute_url()).content.decode()

    def test_identity_where_and_regulator(self):
        content = self.detail('TEST PLANT')
        # Sector as a tag linking to its page; SIC on the grey identifiers line.
        assert re.search(r'<a class="tag[^"]*" href="/tools/emissions/sectors/glass/', content)
        assert 'class="identifiers has-text-grey"' in content and 'SIC 3221' in content
        # The address as reported, and the regulator's card.
        assert '123 Main St' in content and 'Fresno, CA 93728' in content
        # The county is in Counted in, not repeated in the address.
        assert 'Fresno, CA 93728 · Fresno County' not in content
        # The regulator is one line under the tags, not a card.
        assert re.search(r'<p class="facility-regulator">\s*Regulated by', content)
        assert 'San Joaquin Valley APCD' in content
        assert 'card-header-title">Regulated by' not in content
        # The district's phone is tappable, and the complaint form is the page's one button.
        assert 'href="tel:5592306000"' in content
        assert re.search(r'<a class="button[^"]*" href="https://ww2.valleyair.org/file-a-complaint"', content)

    def test_minor_source_tag(self):
        content = self.detail('TEST GAS STATION')
        assert re.search(r'<a class="tag[^"]*" href="/tools/emissions/about/#minor-sources"', content)

    def test_no_complaint_form_keeps_the_phone(self):
        content = self.detail('TEST CEMENT')
        assert 'href="tel:6618625250"' in content
        assert 'Report an air pollution problem' not in content

    def test_inside_an_ab617_community_is_linked(self):
        community = make(Region.Type.AB617_COMMUNITY, 'Shafter', AROUND_PLANT)
        content = self.detail('TEST PLANT')
        assert f'Inside the <a href="{community.get_emissions_url()}' in content
        assert 'Shafter AB 617 community' in content

    def test_no_ab617_line_outside_a_community(self):
        make(Region.Type.AB617_COMMUNITY, 'Shafter', AROUND_PLANT)
        content = self.detail('TEST CEMENT')
        assert 'AB 617 community' not in content

    def test_stat_row_leads_with_the_scope_pollutant(self):
        content = self.detail('TEST PLANT')
        stats = content[content.index('facility-stats'):content.index('Emissions in 2024')]
        assert '<p class="heading">Nitrogen oxides, 2024</p>' in stats
        assert ' in Fresno County</p>' in stats and '#1 of ' in stats
        # The stat row comes before the table, and the map after it.
        assert content.index('facility-stats') < content.index('Emissions in 2024') < content.index('id="where"')

    def test_no_stat_row_without_anything_to_lead_with(self):
        # TEST CEMENT reported no SOx, and has no GHG report or Hot Spots score.
        url = Facility.objects.get(name='TEST CEMENT').get_absolute_url()
        assert 'facility-stats' not in self.client.get(url + '?pollutant=sox').content.decode()

    def test_a_placed_facility_gets_its_map(self):
        content = self.detail('TEST PLANT')
        assert 'class="facility-map' in content
        assert 'No map:' not in content

    def test_an_unplaced_facility_gets_a_line_not_a_valley_map(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        content = self.detail('TEST PLANT')
        assert 'class="facility-map' not in content
        assert "No map: this facility's address couldn't be placed" in content


class HomeSearchTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_find_a_facility_sits_beside_find_your_area(self):
        cache.clear()
        from django.urls import reverse

        content = self.client.get(reverse('emissions:home'), {'minor': '1'}).content.decode()
        row = content[content.index('class="columns find-row"'):]
        assert row.index('id="find"') < row.index('class="box find-facility"') < row.index('Top facilities · ')
        # The search keeps the scope, and there's only one facility search on the page.
        assert '<input type="hidden" name="minor" value="1">' in row[:row.index('Top facilities · ')]
        assert content.count('id="facility-search"') == 1

    def test_top_facilities_and_sectors_are_cards(self):
        cache.clear()
        from django.urls import reverse

        content = self.client.get(reverse('emissions:home')).content.decode()
        facilities = content[content.index('Top facilities · 2024'):content.index('Top sectors · 2024')]
        # TEST PLANT is the fixture's top NOx emitter; the card links it and the full list.
        assert '>TEST PLANT</a>' in facilities
        assert f'href="{reverse("emissions:facility-list")}">View all</a>' in facilities
        sectors = content[content.index('Top sectors · 2024'):]
        assert f'href="{reverse("emissions:sector-list")}">View all</a>' in sectors
        assert '<table class="table is-fullwidth is-hoverable is-narrow facility-table' not in content

    def test_ab617_communities_are_listed_under_the_counties(self):
        cache.clear()
        from django.urls import reverse

        community = make(Region.Type.AB617_COMMUNITY, 'Plantville', AROUND_PLANT)
        content = self.client.get(reverse('emissions:home')).content.decode()
        counties = content.index('Or jump to a county:')
        ab617 = content.index('AB 617 communities:')
        assert counties < ab617
        assert f'href="{community.get_emissions_url()}' in content[ab617:]
        assert 'data-tooltip="Communities CARB has selected under AB 617' in content


class FacilityToxicsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')

    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_toxics_table_order_flags_and_links(self):
        content = self.detail(self.plant)
        table = content[content.index('toxics-table'):content.index('toxics-lead')]
        assert table.index('Benzene') < table.index('Isopropyl alcohol')
        assert 'pollutant=benzene' in table and 'no OEHHA cancer value' in table
        assert table.count('hazard-dot') == 1
        assert '1.9%' in table  # 0.4466 / 23.65825
        assert 'What this is, and isn' in content

    def test_ammonia_row_is_not_in_the_toxics_table(self):
        content = self.detail(self.plant)
        table = content[content.index('toxics-table'):content.index('toxics-lead')]
        assert 'Ammonia' not in table

    def test_hot_spots_card_and_its_absence(self):
        assert 'Hot Spots (AB 2588)' not in self.detail(self.plant)
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(total_score=12.5, hra=4.27)
        content = self.detail(self.plant)
        assert 'Hot Spots (AB 2588)' in content and 'High priority above 10' in content
        assert 'public notification at 10, risk reduction required at 100' in content
        assert 'Chronic hazard index' not in content
        assert 'air-toxics-annual-reports' in content
        # The score also leads the page, in the stat row.
        assert '<p class="heading">Hot Spots priority score</p><p class="title">12.5</p>' in content

    def test_no_toxics_no_table(self):
        cement = Facility.objects.get(name='TEST CEMENT')
        ToxicEmission.objects.filter(facility=cement).delete()
        assert 'toxics-table' not in self.detail(cement)


class SchoolsCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        from camp.apps.emissions.tests.test_schools import location, north_of
        self.plant = Facility.objects.get(name='TEST PLANT')
        location('NEAR ELEMENTARY', north_of(self.plant.point, 900))
        location('QUARTER MILE ACADEMY', north_of(self.plant.point, 1200))
        location('FAR HIGH', north_of(self.plant.point, 2000))

    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_card_groups_and_map_overlay(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.detail(self.plant)
        start = content.index('card-header-title">Schools and child care nearby')
        card = content[start:content.index('<h2', start)]
        assert card.index('Within 1,000 ft') < card.index('NEAR ELEMENTARY') < card.index('1,000 ft to ¼ mile') < card.index('QUARTER MILE ACADEMY')
        assert 'FAR HIGH' not in card
        assert re.search(r'NEAR ELEMENTARY.*?Public school · \d{3} ft', card, re.S)
        assert ' more</p>' not in card  # no "and N more" with one or two rows
        assert map_data(content, 'ring-miles') == '0.25'
        nearby = map_data(content, 'nearby')
        assert 'NEAR ELEMENTARY' in nearby and 'FAR HIGH' not in nearby and '&quot;FeatureCollection&quot;' in nearby
        assert 'href="/tools/emissions/about/#schools"' in card

    def test_none_within_a_quarter_mile(self):
        from camp.apps.regions.models import Location
        Location.objects.exclude(name='FAR HIGH').delete()
        content = self.detail(self.plant)
        assert 'None within ¼ mile.' in content
        assert 'Within 1,000 ft' not in content

    def test_and_n_more(self):
        from camp.apps.emissions.tests.test_schools import location, north_of
        for i in range(11):
            location(f'CROWD {i}', north_of(self.plant.point, 400 + i))
        content = self.detail(self.plant)
        assert 'and 2 more' in content  # 12 within 1,000 ft, 10 shown

    def test_hidden_for_an_untrusted_point(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.detail(Facility.objects.get(name='TEST GAS STATION'))  # point_source maptiler
        assert 'Schools and child care nearby' not in content
        assert map_data(content, 'nearby') == '' and map_data(content, 'ring-miles') == ''

    def test_about_page_explains_the_distances(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="schools">' in content
        assert 'Health &amp; Safety Code 42301.6' in content and 'Education Code 17213' in content
        assert 'Child care covers licensed centers only, not family child-care homes.' in content


class FacilityAmmoniaRowTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def test_ammonia_row_in_the_emissions_table(self):
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        section = content[content.index('Emissions in 2024'):]
        table = section[:section.index('</table>')]
        assert 'pollutant=nh3' in table and 'Ammonia' in table
        content = self.client.get(Facility.objects.get(name='TEST CEMENT').get_absolute_url()).content.decode()
        # TEST CEMENT reported no ammonia: no row for it. The criteria
        # pollutants it didn't report are named in one line under the table.
        section = content[content.index('Emissions in 2024'):]
        table = section[:section.index('</table>')]
        assert 'Ammonia' not in table
        assert 'Not reported in 2024: ROG, SOx, CO, TOG.' in section


class MethaneCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        from camp.apps.emissions.importers import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, NEAR_BOTH, row
        from camp.apps.emissions.tests.test_dairies import make_dairies
        cache.clear()
        make_dairies()
        Facility.objects.filter(name='TEST PLANT').update(point_source=Facility.PointSource.CENSUS)
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([row(name='near', lnglat=NEAR_BOTH, rate='120', unc='40'), row(name='og', lnglat=AT_GAS_STATION, sector='1B2')])

    def detail(self, name):
        return self.client.get(Facility.objects.get(name=name).get_absolute_url()).content.decode()

    def test_card_rows(self):
        content = self.detail('TEST PLANT')
        assert 'card-header-title">Methane plumes observed nearby' in content
        assert '120 ± 40 kg/h' in content
        assert '5 detections of 12 passes' in content and 'Source record →' in content
        # Carbon Mapper is credited on the About and data provider pages, not on every page.
        assert 'Data by Carbon Mapper' not in content and 'Carbon Mapper estimate' not in content
        assert 'BIG DAIRY' in content  # the nearest dairy is named
        assert 'not an annual total' in content

    def test_card_is_hidden_for_oil_gas_groupings(self):
        from camp.apps.emissions.models import MethaneSource
        assert MethaneSource.objects.get(source_name='og').facility.name == 'TEST GAS STATION'
        assert 'Methane plumes observed nearby' not in self.detail('TEST GAS STATION')

    def test_no_card_without_a_source(self):
        assert 'Methane plumes observed nearby' not in self.detail('TEST CEMENT')
