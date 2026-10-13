from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, wells
from camp.apps.emissions.models import EmissionsRecord, Facility, ToxicEmission, ToxicPollutant, Well
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.regions.models import Location, Region

# One degree of latitude is about 364,000 ft: a point `feet` north of another, to within ~0.3%.
FEET_PER_DEGREE_LAT = 364_000


def north_of(point, feet):
    return Point(point.x, point.y + feet / FEET_PER_DEGREE_LAT, srid=4326)


def make_well(api, lnglat, county, status='Active', hpz='Not Within HPZ', **fields):
    point = lnglat if isinstance(lnglat, Point) else Point(*lnglat, srid=4326)
    fields = {'operator_name': 'TEST OIL LLC', 'field_name': 'Test Field', 'well_type_label': 'Oil & Gas', **fields}
    return Well.objects.create(
        api=api, lease_name='TEST LEASE', well_number=api[-2:], status=status, in_hpz=hpz, county=county, point=point, **fields,
    )


def location(name, point, type=Location.Type.PUBLIC_SCHOOL):
    return Location.objects.create(name=name, type=type, external_id=name, source='test', point=point)


class WellsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')  # (-119.787, 36.737)
        self.a = make_well('0402900001', IN_KERN, self.kern)
        self.b = make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), self.kern, status='Idle', hpz='Verified HPZ')
        self.c = make_well('0402900003', (IN_KERN[0] + 0.002, IN_KERN[1]), self.kern, status='New', hpz='Verified HPZ')
        self.d = make_well('0401900004', NEAR_PLANT, self.fresno)


class AreaSummaryTests(WellsTestCase):
    def test_counts_by_county_point_and_radius(self):
        assert wells.area_summary(areas.RegionArea(self.kern)) == {'total': 3, 'active': 1, 'idle': 1, 'new': 1, 'hpz': 2}
        assert wells.area_summary(areas.RegionArea(self.fresno)) == {'total': 1, 'active': 1, 'idle': 0, 'new': 0, 'hpz': 0}
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert wells.area_summary(areas.RegionArea(tract))['total'] == 1
        assert wells.area_summary(areas.RadiusArea(36.737, -119.787, 1))['total'] == 1
        assert wells.area_summary(areas.RadiusArea(36.0, -120.5, 1)) is None
        assert wells.area_summary(areas.RegionArea(Region.objects.get(type=Region.Type.COUNTY, slug='tulare'))) is None

    def test_cached_under_the_generation(self):
        area = areas.RegionArea(self.kern)
        assert wells.area_summary(area)['total'] == 3
        make_well('0402900009', IN_KERN, self.kern)
        assert wells.area_summary(area)['total'] == 3
        wells.clear_caches()
        assert wells.area_summary(area)['total'] == 4


class SchoolsNearWellsTests(WellsTestCase):
    def setUp(self):
        super().setUp()
        # Around TEST PLANT: a school with wells at 3,000 and 3,400 ft north, a preschool 200 ft from the Fresno well.
        self.school = location('PLANT ELEMENTARY', self.plant.point)
        make_well('0401900010', north_of(self.plant.point, 3000), self.fresno)
        make_well('0401900011', north_of(self.plant.point, 3400), self.fresno)
        self.preschool = location('OILFIELD PRESCHOOL', north_of(Point(*NEAR_PLANT, srid=4326), 200), Location.Type.CHILD_CARE)
        self.far = location('FAR HIGH', Point(-120.5, 36.0, srid=4326))

    def test_schools_near_wells_boundary(self):
        counts = wells.locations_near_wells()
        # 3,000 ft well in, 3,400 ft well out; the WellsTestCase well by NEAR_PLANT is
        # ~935 ft from the school (also in) -- 2 total, matching test_area_rows below.
        assert counts[self.school.pk] == 2
        assert self.far.pk not in counts

    def test_area_rows(self):
        result = wells.schools_near_wells(areas.RegionArea(self.fresno))
        assert result['count'] == 2
        assert [(row['name'], row['wells'], row['type_label']) for row in result['top']] == [
            ('PLANT ELEMENTARY', 2, 'Public school'), ('OILFIELD PRESCHOOL', 1, 'Child care'),
        ]
        assert result['top'][0]['sqid'] == self.school.sqid
        assert wells.schools_near_wells(areas.RegionArea(self.kern)) == {'count': 0, 'top': []}
        near = wells.schools_near_wells(areas.RadiusArea(36.737, -119.787, 1))
        assert near['count'] == 2

    def test_top_ten(self):
        for i in range(12):
            location(f'CROWD {i}', north_of(self.plant.point, 100 + i))
        result = wells.schools_near_wells(areas.RegionArea(self.fresno))
        assert result['count'] == 14 and len(result['top']) == wells.SCHOOL_TOP


class KernCalloutTests(WellsTestCase):
    def test_shares(self):
        # Kern 2024: TEST GAS STATION reported 0.2 tons ROG and 0.5 lbs benzene (the fixture); add an oil-gas grouping.
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=77, name='HEAVY OIL WESTERN',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.8')
        ToxicEmission.objects.create(facility=rig, year=2024, pollutant=ToxicPollutant.objects.get(carb_id='71432'), lbs='3')
        callout = wells.kern_callout(2024)
        assert callout['year'] == 2024 and callout['facilities'] == 1
        assert abs(callout['rog_share'] - 0.8) < 1e-9 and abs(callout['benzene_share'] - 3 / 3.5) < 1e-9

    def test_none_without_data(self):
        assert wells.kern_callout(1999) is None
        EmissionsRecord.objects.filter(facility__county=self.kern).update(rog=None)
        cache.clear()
        assert wells.kern_callout(2024) is None

    def test_benzene_share_is_none_without_benzene(self):
        ToxicEmission.objects.filter(facility__county=self.kern).delete()
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=78, name='LIGHT OIL',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.2')
        callout = wells.kern_callout(2024)
        assert abs(callout['rog_share'] - 0.5) < 1e-9 and callout['benzene_share'] is None
