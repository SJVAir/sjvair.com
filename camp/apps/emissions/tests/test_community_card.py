from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.ces.models import CES4, CES5
from camp.apps.emissions.models import Facility
from camp.apps.emissions.tests.test_areas import make
from camp.apps.regions.models import Region

# The fixture tract 1.01 is -119.8..-119.7 (89.2, DAC); TEST PLANT (-119.787, 36.737) is inside it.


class FacilityTractLineTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.tract = Region.objects.get(type=Region.Type.TRACT, external_id='06019000101')

    def test_the_where_card_names_the_tract_percentile(self):
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        start = content.index('class="card facility-place"')
        where = content[start:content.index('</div>', start + 40)]
        assert f'In <a href="{self.tract.get_emissions_url()}">a tract at the 89th percentile</a> (CalEnviroScreen 5.0) · SB 535 disadvantaged community' in where

    def test_no_tract_no_line(self):
        # TEST CEMENT's point is in no fixture tract.
        content = self.client.get(Facility.objects.get(name='TEST CEMENT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content

    def test_about_page_has_no_calenviroscreen_section(self):
        # Only the facility page's Community line uses CalEnviroScreen; the About page lists it as a source.
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert 'id="calenviroscreen"' not in content
        assert 'https://oehha.ca.gov/calenviroscreen' in content
