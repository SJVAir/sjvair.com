from django.db.models import Max, Prefetch
from django.test import TestCase

from . import api
from .forms import PurpleAirAddForm
from .models import PurpleAir


class PurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']
    def setUp(self):
        self.monitor = PurpleAir.objects.get(data__0__ID=8892)

    def test_add_form(self):
        form = PurpleAirAddForm({
            'purple_id': 8854,
            'thingspeak_key': 'LHWBU0JJ70TARXXM'
        })
        assert form.is_valid()
        device = form.save()

        assert device.purple_id == form.cleaned_data['purple_id']
        assert device.thingspeak_key == form.cleaned_data['thingspeak_key']
        assert 'Root Access' in device.name

    def test_create_entry(self):
        feeds = self.monitor.get_feeds(results=1)
        payload = next(feeds['a'])
        entry = self.monitor.create_entry(payload, sensor='a')
        self.monitor.process_entry(entry)

        assert entry.sensor == 'a'
        assert entry.position == self.monitor.position
        assert entry.fahrenheit == entry.payload[0]['Temperature']
        assert entry.pm25_aqi is not None

    # def test_thing(self):
    #     qs = PurpleAir.objects.annotate(
    #         last_updated=Max('entries__timestamp')
    #     )
    #     print(qs.get().last_updated)
