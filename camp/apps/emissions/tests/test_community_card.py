from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.ces.models import CES4, CES5
from camp.apps.emissions.models import Facility
from camp.apps.emissions.tests.test_areas import make
from camp.apps.regions.models import Region

# The fixture tracts: 1.01 is -119.8..-119.7 (89.2, DAC, pop 4650); 1.02 is -119.7..-119.6 (51.0, not DAC, pop 3350).
# TEST PLANT (-119.787, 36.737) is inside 1.01.
TWO_TRACTS = 'MULTIPOLYGON(((-119.74 36.7, -119.6 36.7, -119.6 36.8, -119.74 36.8, -119.74 36.7)))'


class CommunityCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.tract = Region.objects.get(type=Region.Type.TRACT, external_id='06019000101')
        self.other = Region.objects.get(type=Region.Type.TRACT, external_id='06019000102')

    def get(self, url, params=None):
        response = self.client.get(url, params or {})
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def card(self, content):
        assert 'id="community"' in content
        start = content.index('id="community"')
        return content[start:content.index('</div>', content.index('</ul>', start))]

    def test_county_card(self):
        card = self.card(self.get(self.fresno.get_emissions_url(), {'year': '2024'}))
        assert '<strong>58%</strong> of residents live in state-designated disadvantaged communities (SB 535)' in card
        # Template literals aren't HTML-escaped, so the apostrophe is a plain one.
        assert "<strong>1 of 2</strong> census tracts are in California's most burdened 25% (CalEnviroScreen 5.0)" in card
        assert f'<a href="{self.other.get_emissions_url()}">51st</a> to <a href="{self.tract.get_emissions_url()}">89th</a>' in card
        # A county page lists its highest tracts.
        assert 'Highest tracts' in card and card.index('Census Tract 1.01') < card.index('Census Tract 1.02')
        # And the section nav gains a Community link.
        assert '<a href="#community">Community</a>' in self.get(self.fresno.get_emissions_url())

    def test_community_card_without_the_top_list(self):
        place = make(Region.Type.CDP, 'Plantville', TWO_TRACTS)
        card = self.card(self.get(place.get_emissions_url()))
        assert '1 of 2</strong> census tracts' in card and 'Highest tracts' not in card

    def test_near_me_card(self):
        # (-119.78, 36.73) is inside tract 1.01 near TEST PLANT, clear of the tract's centroid (-119.75, 36.75):
        # a 1-mile circle covers ~8% of the tract and neither contains its centroid, so it falls to `containing`;
        # a 3-mile circle reaches the centroid, so the tract counts. (A 302 here means the point fell outside the
        # fixture's Fresno County boundary -- nudge it toward TEST PLANT at (-119.787, 36.737), staying off the centroid.)
        url = reverse('emissions:near-me')
        content = self.get(url, {'lat': '36.73', 'lng': '-119.78', 'radius': '1'})
        card = content[content.index('id="community"'):]
        assert f'Inside census tract <a href="{self.tract.get_emissions_url()}">Census Tract 1.01</a>, at the 89th percentile (CalEnviroScreen 5.0)' in card
        assert 'SB 535 disadvantaged community' in card
        content = self.get(url, {'lat': '36.73', 'lng': '-119.78', 'radius': '3'})
        assert '1 of 1</strong> census tract is in' in content

    def test_tract_page_shows_its_own_scores(self):
        content = self.get(self.tract.get_emissions_url())
        card = content[content.index('id="community"'):]
        assert 'Overall: <strong>89th percentile</strong>' in card
        assert 'Pollution burden: <strong>83rd percentile</strong>' in card
        assert 'SB 535 disadvantaged community (Top 25% CES overall score)' in card
        assert 'https://oehha.ca.gov/calenviroscreen' in card
        assert 'of residents live' not in card

    def test_no_ces_data_no_card(self):
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        for url in (self.fresno.get_emissions_url(), self.tract.get_emissions_url()):
            assert 'id="community"' not in self.get(url)
        assert 'id="community"' not in self.get(reverse('emissions:near-me'), {'lat': '36.73', 'lng': '-119.78'})


class FacilityTractLineTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.tract = Region.objects.get(type=Region.Type.TRACT, external_id='06019000101')

    def test_the_where_card_names_the_tract_percentile(self):
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        start = content.index('card-header-title">Address')
        where = content[start:content.index('</div>\n    </div>', start)]
        assert f'In <a href="{self.tract.get_emissions_url()}">a tract at the 89th percentile</a> (CalEnviroScreen 5.0) · SB 535 disadvantaged community' in where

    def test_no_tract_no_line(self):
        # TEST CEMENT's point is in no fixture tract.
        content = self.client.get(Facility.objects.get(name='TEST CEMENT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content

    def test_about_page(self):
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="calenviroscreen">' in content
        assert "SB 535 disadvantaged-community list shown is CalEPA's 2026 draft until it is final" in content
