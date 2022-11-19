from django.db.models import Max, Prefetch
from django.test import TestCase

from .api import purpleair_api
from .models import PurpleAir


class PurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']
    def setUp(self):
        self.monitor = PurpleAir.objects.get(data__sensor_index=8892)

    def test_create_entry(self):
        payload = purpleair_api.get_sensor(self.monitor.purple_id)
        (a, b) = self.monitor.create_entries(payload)
        self.monitor.process_entry(a)
        self.monitor.process_entry(b)
        self.monitor.check_latest(a)
        self.monitor.check_latest(b)

        import code
        code.interact(local=locals())

        assert a.sensor == 'a'
        assert a.position == self.monitor.position
        assert a.fahrenheit == payload['temperature']

    # def test_thing(self):
    #     qs = PurpleAir.objects.annotate(
    #         last_updated=Max('entries__timestamp')
    #     )
    #     print(qs.get().last_updated)
