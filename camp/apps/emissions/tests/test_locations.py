from io import StringIO

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import locations
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region

SLOVAKIA = Point(19.174, 48.741, srid=4326)


class IsGeocodableTests(TestCase):
    def test_street_addresses(self):
        assert locations.is_geocodable({'street': '123 MAIN ST', 'city': 'FRESNO'})
        assert locations.is_geocodable({'street': '42675 ROAD 44', 'city': 'REEDLEY'})
        assert locations.is_geocodable({'street': '1674 HIGHWAY 99', 'city': 'DELANO'})
        # Street-only: approximate, but the county check guards it.
        assert locations.is_geocodable({'street': 'EUCLID AVE', 'city': 'DINUBA'})

    def test_not_a_site(self):
        assert not locations.is_geocodable({'street': 'VARIOUS LOCATIONS', 'city': 'VARIOUS LOCATIONS'})
        assert not locations.is_geocodable({'street': 'VARIOUS LOCATIONS, SJVAPCD', 'city': ''})
        assert not locations.is_geocodable({'street': '1 MAIN ST', 'city': 'VARIOUS LOCATIONS, S'})
        assert not locations.is_geocodable({'street': '', 'city': 'FRESNO'})
        assert not locations.is_geocodable({})


class PlausibleTests(TestCase):
    fixtures = ['regions.yaml']

    def test_inside_near_and_far(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        area = locations.county_area(fresno)
        assert locations.plausible(Point(-119.787, 36.737, srid=4326), area)
        assert not locations.plausible(SLOVAKIA, area)
        assert not locations.plausible(None, area)

    def test_no_boundary_trusts_the_point(self):
        assert locations.county_area(None) is None
        assert locations.plausible(SLOVAKIA, None)


class CleanFacilityPointsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def run_command(self, *args):
        out = StringIO()
        call_command('clean_facility_points', *args, stdout=out)
        return out.getvalue()

    def test_clears_points_outside_the_county(self):
        Facility.objects.filter(name='TEST PLANT').update(point=SLOVAKIA)
        output = self.run_command()
        assert 'Cleared 1 facility points.' in output
        assert Facility.objects.get(name='TEST PLANT').point is None
        assert Facility.objects.get(name='TEST CEMENT').point is not None
        assert Facility.objects.get(name='TEST GAS STATION').point is not None

    def test_clears_points_geocoded_from_a_non_address(self):
        facility = Facility.objects.get(name='TEST PLANT')
        facility.address = {'street': 'VARIOUS LOCATIONS', 'city': 'VARIOUS LOCATIONS', 'zipcode': ''}
        facility.save()
        self.run_command()
        assert Facility.objects.get(name='TEST PLANT').point is None

    def test_dry_run_writes_nothing(self):
        Facility.objects.filter(name='TEST PLANT').update(point=SLOVAKIA)
        output = self.run_command('--dry-run')
        assert 'Would clear 1 facility points.' in output
        assert Facility.objects.get(name='TEST PLANT').point == SLOVAKIA

    def test_nothing_to_clear(self):
        assert 'Cleared 0 facility points.' in self.run_command()
