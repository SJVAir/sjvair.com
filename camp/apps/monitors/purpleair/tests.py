from django.db.models import Max, Prefetch
from django.test import TestCase

from .api import purpleair_api
from .forms import PurpleAirAddForm
from .models import PurpleAir


class PurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']
    def setUp(self):
        self.monitor = PurpleAir.objects.get(data__sensor_index=8892)

    def test_add_form(self):
        form = PurpleAirAddForm({
            'purple_id': 8854,
            'thingspeak_key': 'LHWBU0JJ70TARXXM'
        })
        assert form.is_valid()
        monitor = form.save()

        assert monitor.purple_id == form.cleaned_data['purple_id']
        # assert monitor.thingspeak_key == form.cleaned_data['thingspeak_key']
        assert 'Root Access' in monitor.name

    def test_create_entry(self):
        payload = purpleair_api.get_sensor(self.monitor.data['sensor_index'])
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
