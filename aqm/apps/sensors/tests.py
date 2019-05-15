import json

from django.test import TestCase, RequestFactory
from django.urls import reverse

from . import views
from .models import Sensor, SensorData

sensor_list = views.SensorList.as_view()
sensor_detail = views.SensorDetail.as_view()
sensor_data = views.SensorData.as_view()


def streaming_json(stream):
    return json.loads(''.join([b.decode('utf8') for b in stream]))


class SensorTests(TestCase):
    fixtures = ['sensors.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.sensor = Sensor.objects.get(name='RAHS')

    def test_sensor_list(self):
        url = reverse('sensors:sensor-list')
        request = self.factory.get(url)
        response = sensor_list(request)
        assert response.status_code == 200

        content = streaming_json(response.streaming_content)
        assert content['data'][0]['id'] == str(self.sensor.pk)

    def test_sensor_detail(self):
        url = reverse('sensors:sensor-detail', kwargs={'sensor_id': self.sensor.pk})
        request = self.factory.get(url)
        response = sensor_detail(request, sensor_id=self.sensor.pk)
        assert response.status_code == 200

        content = json.loads(response.content)
        assert content['data']['id'] == str(self.sensor.pk)
