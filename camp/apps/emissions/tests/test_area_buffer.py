from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas
from camp.apps.emissions.models import Facility
from camp.apps.emissions.tests.test_areas import make
from camp.apps.emissions.tests.test_dairies import make_dairies
from camp.apps.regions.models import Region

# A town just west of TEST PLANT (-119.787, 36.737): the plant is about half a mile past its edge.
WEST_TOWN = 'MULTIPOLYGON(((-119.8 36.72, -119.795 36.72, -119.795 36.75, -119.8 36.75, -119.8 36.72)))'


class AreaBufferTests(TestCase):
    """A region page widened past its boundary (?buffer=) lists and counts what its map shows."""
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.town = make(Region.Type.CITY, 'West Town', WEST_TOWN)
        self.plant = Facility.objects.get(name='TEST PLANT')

    def get(self, tab, params=None, table=False):
        url = self.town.get_emissions_tab_url(tab) + ('table/' if table else '')
        response = self.client.get(url, {'year': '2024', **(params or {})})
        assert response.status_code == 200
        return response.content.decode()

    def test_the_area_reaches_past_the_boundary(self):
        exact = areas.RegionArea(self.town)
        widened = areas.RegionArea(self.town, 1)
        assert not Facility.objects.filter(pk=self.plant.pk).filter(**{'point__intersects': exact.geometry}).exists()
        assert widened.key != exact.key
        assert widened.sq_miles > exact.sq_miles
        assert widened.population is None

    def test_the_table_and_its_search_include_the_band(self):
        assert 'Test Plant' not in self.get('facilities', table=True)
        assert 'Test Plant' in self.get('facilities', {'buffer': '1'}, table=True)
        assert 'Test Plant' in self.get('facilities', {'buffer': '1', 'q': 'plant'}, table=True)
        assert 'Test Plant' not in self.get('facilities', {'buffer': '1', 'q': 'cement'}, table=True)

    def test_the_page_keeps_the_buffer_and_says_so(self):
        content = self.get('facilities', {'buffer': '3'})
        assert 'Including 3 miles past the boundary' in content
        assert f'href="{self.town.get_emissions_tab_url("facilities")}?year=2024"' in content  # Exact boundary
        assert '<input type="hidden" name="buffer" value="3">' in content
        assert f'href="{self.town.get_emissions_tab_url("overview")}?buffer=3"' in content
        assert 'Share of' not in content
        assert 'area-buffer-note' not in self.get('facilities')

    def test_the_dairy_page_keeps_the_buffer(self):
        make_dairies()
        content = self.client.get(self.town.get_emissions_dairies_url(), {'buffer': '1'}).content.decode()
        form = content[content.index('id="dairy-filters"'):]
        assert '<input type="hidden" name="buffer" value="1">' in form[:form.index('</form>')]
        assert 'Including 1 mile past the boundary' in content
