from django.contrib.gis.geos import GEOSGeometry
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Boundary, Region

# TEST PLANT is at (-119.787, 36.737): Fresno. TEST CEMENT is at (-118.17, 35.05).
AROUND_PLANT = 'MULTIPOLYGON(((-119.8 36.72, -119.77 36.72, -119.77 36.75, -119.8 36.75, -119.8 36.72)))'
WEST_OF_PLANT = 'MULTIPOLYGON(((-119.8 36.72, -119.787 36.72, -119.787 36.75, -119.8 36.75, -119.8 36.72)))'
EAST_OF_PLANT = 'MULTIPOLYGON(((-119.787 36.72, -119.77 36.72, -119.77 36.75, -119.787 36.75, -119.787 36.72)))'


def make(region_type, name, wkt, *, version='2020', population=None):
    metadata = {'population': population} if population is not None else {}
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=region_type,
                                   external_id=name, metadata=metadata)
    boundary = Boundary.objects.create(region=region, version=version, geometry=GEOSGeometry(wkt, srid=4326))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


class AreaTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        # 2024, NOx: the plant reported 6.0 tons, the cement plant 100.0.
        self.scope = stats.resolve_scope({'year': '2024', 'pollutant': 'nox'})


class RegionIndexTests(AreaTestCase):
    def test_zip_and_tract_by_point(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        index = areas.region_index(Region.Type.TRACT)
        assert index[self.plant.pk] == tract.pk
        assert self.cement.pk not in index

    def test_retired_tracts_are_not_used(self):
        make(Region.Type.TRACT, 'Old', AROUND_PLANT, version='2010')
        assert self.plant.pk not in areas.region_index(Region.Type.TRACT)

    def test_a_facility_on_a_shared_border_counts_once(self):
        make(Region.Type.TRACT, 'West', WEST_OF_PLANT)
        make(Region.Type.TRACT, 'East', EAST_OF_PLANT)
        values = areas.area_values(self.scope, Region.Type.TRACT)
        assert sum(area['facilities'] for area in values['areas']) == 1

    def test_county_level_uses_carbs_county_code(self):
        index = areas.region_index(Region.Type.COUNTY)
        assert index[self.plant.pk] == self.plant.county_id
        assert index[self.cement.pk] == self.cement.county_id


class AreaValuesTests(AreaTestCase):
    def test_measures(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT, population=2000)
        values = areas.area_values(self.scope, Region.Type.TRACT)
        assert values['level'] == 'tract' and values['unit'] == 'tons'
        [area] = values['areas']
        miles = areas.region_sq_miles(Region.Type.TRACT)[tract.pk]
        assert area['id'] == tract.sqid
        assert area['facilities'] == 1
        assert area['total'] == 6.0
        assert abs(area['per_sq_mi'] - 6.0 / miles) < 1e-9
        assert area['per_1k_residents'] == 3.0

    def test_no_or_zero_population_has_no_per_resident_value(self):
        make(Region.Type.TRACT, 'West', WEST_OF_PLANT, population=0)
        make(Region.Type.TRACT, 'Far', 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))')
        for area in areas.area_values(self.scope, Region.Type.TRACT)['areas']:
            assert area['per_1k_residents'] is None

    def test_toxics_in_pounds(self):
        make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        scope = stats.resolve_scope({'year': '2024', 'toxics': '1'})
        assert areas.area_values(scope, Region.Type.TRACT)['unit'] == 'lbs'

    def test_sector_filter(self):
        make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert areas.area_values(self.scope, Region.Type.TRACT, sector='cement-minerals')['areas'] == []


class ScopeAreaTests(AreaTestCase):
    def test_region_area_narrows_every_aggregate(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT, population=1500)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=areas.RegionArea(tract))
        assert stats.totals(scope)['facilities'] == 1
        assert stats.totals(scope)['nox'] == 6.0
        assert scope.key('totals') != self.scope.key('totals')
        assert scope.area.population == 1500 and scope.area.sq_miles > 0

    def test_city_area_is_by_point(self):
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=areas.RegionArea(city))
        assert stats.totals(scope)['facilities'] == 1

    def test_radius_area(self):
        near = areas.RadiusArea(36.737, -119.787, 1)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=near)
        assert stats.totals(scope)['facilities'] == 1
        assert abs(near.sq_miles - 3.14159) < 0.001

    def test_facility_areas(self):
        # The fixture's ZIP 93728 contains the plant too; start from none.
        Region.objects.filter(type=Region.Type.ZIPCODE).delete()
        zipcode = make(Region.Type.ZIPCODE, '93701', AROUND_PLANT)
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert areas.facility_areas(self.plant) == [self.plant.county, zipcode, tract]
        assert areas.facility_areas(self.cement) == [self.cement.county]
