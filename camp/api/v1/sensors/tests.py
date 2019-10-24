import json
import random

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from resticus.encoders import JSONEncoder

from . import endpoints
from camp.apps.sensors.models import Sensor, SensorData
from camp.utils.test import get_response_data

sensor_list = endpoints.SensorList.as_view()
sensor_detail = endpoints.SensorDetail.as_view()
sensor_data = endpoints.SensorData.as_view()


def random_trend(low, high, num, reverse=False):
    # Not sure if this is an alright way to generate
    # a pseudo-random trend-y list, but we'll see...
    data = []
    value = random.randint(0, high - random.randint(0, high / 2))
    for x in range(num):
        value = int(round(random.triangular(low, high, value)))
        data.append(value)
    return sorted(data, reverse=reverse)


def fake_sensor_payload():
    '''
        Helper to generate a pseudo-random payload object
    '''
    pm2_trend = random_trend(0, 700, 3)
    pm2_std = list(zip(('pm10_standard', 'pm25_standard', 'pm100_standard'), pm2_trend))
    pm2_env = list(zip(
        ('pm10_env', 'pm25_env', 'pm100_env'),
        [x + random.randint(-10, 10) for x in pm2_trend]
    ))

    particle_trend = random_trend(0, 700, 6, reverse=True)
    particles = list(zip((
        'particles_03um',
        'particles_05um',
        'particles_10um',
        'particles_25um',
        'particles_50um',
        'particles_100um'
    ), particle_trend))

    return dict(
        celcius=random.randint(100, 400) / 10, # 10-40C (50-104F)
        humidity=random.randint(300, 700) / 10, # 30-70% RH
        pressure=0, # TODO
        voc=0, # TODO
        pm2_a=dict(pm2_std + pm2_env + particles),
        pm2_b={k: v + random.randint(-10, 10) for k, v in (pm2_std + pm2_env + particles)},
    )


def fake_sensor_data(sensor, payload=None, process=True, save=True):
    data = SensorData(
        sensor=sensor,
        position=sensor.position,
        payload=payload or fake_sensor_payload(),
    )
    if process:
        data.process()
    if save:
        data.save()
    return data


class SensorAPITests(TestCase):
    fixtures = ['sensors.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.sensor = Sensor.objects.get(name='Root Access Hackerspace')

    def test_get_sensor_list(self):
        url = reverse('api:v1:sensors:sensor-list')
        request = self.factory.get(url)
        response = sensor_list(request)
        assert response.status_code == 200

        content = get_response_data(response)
        assert str(self.sensor.pk) in [sensor['id'] for sensor in content['data']]

    def test_get_sensor_detail(self):
        url = reverse('api:v1:sensors:sensor-detail', kwargs={'sensor_id': self.sensor.pk})
        request = self.factory.get(url)
        response = sensor_detail(request, sensor_id=self.sensor.pk)
        assert response.status_code == 200

        content = get_response_data(response)
        assert content['data']['id'] == str(self.sensor.pk)

    def test_get_sensor_data(self):
        now = timezone.now()
        for x in range(10):
            data = fake_sensor_data(sensor=self.sensor, save=False)
            data.timestamp = now - timedelta(minutes=10 * x)
            data.save()

        url = reverse('api:v1:sensors:sensor-data', kwargs={'sensor_id': self.sensor.pk})
        request = self.factory.get(url)
        response = sensor_data(request, sensor_id=self.sensor.pk)
        assert response.status_code == 200

        content = get_response_data(response)
        assert len(content['data'])

    def test_create_sensor_data(self):
        payload = fake_sensor_payload()
        url = reverse('api:v1:sensors:sensor-data', kwargs={'sensor_id': self.sensor.pk})
        request = self.factory.post(url, {'payload': payload}, content_type='application/json')
        response = sensor_data(request, sensor_id=self.sensor.pk)
        assert response.status_code == 200

        content = get_response_data(response)
        sensor = Sensor.objects.get(pk=self.sensor.pk)

        assert content['data']['sensor'] == str(self.sensor.pk)
        assert content['data']['id'] == str(sensor.latest_id)
