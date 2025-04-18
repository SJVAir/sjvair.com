from django.db.models import Max, Prefetch
from django.test import TestCase

from .api import purpleair_api
from .models import PurpleAir


class PurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']
    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_create_entry_legacy(self):
        payload = purpleair_api.get_sensor(self.monitor.purple_id)
        (a, b) = self.monitor.create_entries_legacy(payload)
        self.monitor.check_latest(a)
        self.monitor.check_latest(b)

        assert a.sensor == 'a'
        assert a.position == self.monitor.position
        assert a.fahrenheit == payload['temperature']

    def test_probable_location_marked_inside(self):
        payload = {'name': 'test', 'location_type': 1}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.inside

    def test_probable_location_marked_outside_name_implies_inside(self):
        payload = {'name': 'test indoor', 'location_type': 0}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.inside

    def test_probable_location_marked_outside(self):
        payload = {'name': 'test outdoor', 'location_type': 0}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.outside
