from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, schools, stats
from camp.apps.emissions.models import Facility
from camp.apps.emissions.pollutants import get_pollutant
from camp.apps.emissions.tests.test_dairies import make_dairy
from camp.apps.emissions.tests.test_wells import location, make_well, north_of
from camp.apps.regions.models import Location, Region


class SchoolSitesTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')  # census point, (-119.787, 36.737)
        # 500 ft and 1,200 ft north of TEST PLANT, and a center well clear of it.
        self.close = location('CLOSE ELEMENTARY', north_of(self.plant.point, 500))
        self.quarter = location('QUARTER CARE', north_of(self.plant.point, 1200), type=Location.Type.CHILD_CARE)
        self.far = location('FAR HIGH', north_of(self.plant.point, 9000))
        make_dairy(9001, 'NEAR DAIRY', (self.plant.point.x, self.plant.point.y + 0.01), self.fresno,
                   herds={2023: {'milk_cows': 500}})
        make_well('0401900001', north_of(self.plant.point, 2000), self.fresno)

    def scope(self, **kwargs):
        return stats.Scope(year=2024, county=None, pollutant=get_pollutant('nox'), **kwargs)

    def rows(self, **filters):
        return {row['name']: row for row in schools.area_sites(areas.RegionArea(self.fresno), self.scope(), **filters)}


class SiteIndexTests(SchoolSitesTestCase):
    def test_counts_each_source_at_its_distance(self):
        rows = self.rows()
        close, quarter, far = rows['CLOSE ELEMENTARY'], rows['QUARTER CARE'], rows['FAR HIGH']
        assert (close['notice'], close['quarter']) == (1, 1)
        assert (quarter['notice'], quarter['quarter']) == (0, 1)
        assert (far['notice'], far['quarter']) == (0, 0)
        # The well is 1,500 ft from CLOSE and 800 ft from QUARTER: both within 3,200 ft; FAR is 7,000 ft away.
        assert (close['wells'], quarter['wells'], far['wells']) == (1, 1, 0)
        # The dairy is ~0.69 mi north of the plant: within a mile of CLOSE and QUARTER, ~1.02 mi from FAR.
        assert (close['dairies'], quarter['dairies'], far['dairies']) == (1, 1, 0)
        assert close['value'] is not None and far['value'] is None

    def test_an_untrusted_point_doesnt_count(self):
        Facility.objects.filter(pk=self.plant.pk).update(point_source='maptiler')
        assert self.rows()['CLOSE ELEMENTARY']['quarter'] == 0

    def test_filters_and_sort(self):
        assert list(self.rows(type='child-care')) == ['QUARTER CARE']
        assert set(self.rows(q='high')) == {'FAR HIGH'}
        Location.objects.filter(pk=self.far.pk).update(point=north_of(self.plant.point, 40000))
        cache.clear()
        assert 'FAR HIGH' not in self.rows(near=True)
        names = [row['name'] for row in schools.area_sites(areas.RegionArea(self.fresno), self.scope(), sort='-notice')]
        assert names[0] == 'CLOSE ELEMENTARY'
        names = [row['name'] for row in schools.area_sites(areas.RegionArea(self.fresno), self.scope(), sort='name')]
        assert names == sorted(names)

    def test_summary(self):
        summary = schools.site_summary(list(self.rows().values()))
        assert summary == {'schools': 2, 'child_care': 1, 'quarter': 2, 'notice': 1, 'wells': 2, 'dairies': 2}


class SchoolsTabTests(SchoolSitesTestCase):
    def test_the_tab(self):
        url = self.fresno.get_emissions_tab_url('schools')
        content = self.client.get(url, {'year': '2024'}).content.decode()
        assert 'site-table' in content and 'CLOSE ELEMENTARY' in content
        assert 'Facility within ¼ mile' in content
        assert f'href="{url}' in self.client.get(self.fresno.get_emissions_url()).content.decode()
        response = self.client.get(url, {'format': 'csv', 'year': '2024'})
        assert response['Content-Type'] == 'text/csv'
        lines = response.content.decode().strip().splitlines()
        assert lines[0].startswith('name,type,latitude,longitude,facilities_within_1000ft') and len(lines) == 4

    def test_no_tab_without_sites(self):
        content = self.client.get(self.kern.get_emissions_url()).content.decode()
        assert self.kern.get_emissions_tab_url('schools') not in content

    def test_near_me(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:near-me-schools'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1'}).content.decode()
        assert 'CLOSE ELEMENTARY' in content and 'FAR HIGH' not in content
