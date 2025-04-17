from decimal import Decimal
from pprint import pprint

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import endpoints

from camp.apps.entries import models as entry_models
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware, parse_datetime
from camp.utils.test import debug, get_response_data

monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
entry_list = endpoints.EntryList.as_view()


from datetime import datetime, timedelta
from decimal import Decimal
import random
import pytz

def generate_sensor_value(mean, variance):
    return Decimal(str(round(random.gauss(mean, variance), 2)))

def create_hourly_data_for_monitor(monitor, start_time=None):
    if start_time is None:
        start_time = datetime.now(tz=pytz.UTC) - timedelta(hours=1)

    entry_config = monitor.ENTRY_CONFIG
    for i in range(60):  # One per minute
        entries = []
        timestamp = start_time + timedelta(minutes=i)

        for EntryModel, config in entry_config.items():
            sensors = config.get('sensors', [''])  # Default to empty string sensor
            for sensor in sensors:
                fields = {}
                for field, api_field in config.get('fields', {}).items():
                    if 'pm25' in field:
                        fields[field] = generate_sensor_value(15, 5)
                    elif 'pm10' in field:
                        fields[field] = generate_sensor_value(10, 3)
                    elif 'pm100' in field:
                        fields[field] = generate_sensor_value(20, 7)
                    elif 'temperature' in field:
                        fields[field] = generate_sensor_value(75, 5)
                    elif 'humidity' in field:
                        fields[field] = generate_sensor_value(40, 10)
                    elif 'pressure' in field:
                        fields[field] = generate_sensor_value(1013, 5)
                    elif 'particles' in field:
                        fields[field] = generate_sensor_value(100 * (1 + random.random()), 20)
                    else:
                        fields[field] = generate_sensor_value(5, 2)

                entry = monitor.create_entry(
                    EntryModel,
                    timestamp=timestamp,
                    sensor=sensor,
                    **fields
                )
                
                entries.append(entry)

        monitor.calibrate_entries(entries)


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def get_purple_air(self):
        return PurpleAir.objects.get(purple_id=8892)

    def get_bam1022(self):
        return BAM1022.objects.get(name='CCAC')

    def test_monitor_list(self):
        '''
            Test that we can GET the monitor list endpoint.
        '''
        url = reverse('api:v2:monitors:monitor-list')
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_current_data(self):
        '''
            Test that we can GET the current data endpoint.
        '''
        url = reverse('api:v2:monitors:current-data', kwargs={
            'entry_type': 'pm25',
        })
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_monitor_detail(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        monitor = self.get_purple_air()
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = monitor
        response = monitor_detail(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['id'] == str(monitor.pk)

    def test_entry_list(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()
        create_hourly_data_for_monitor(monitor)

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        request = self.factory.get(url)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['sensor'] for e in content['data']} == set([monitor.get_default_sensor(entry_models.PM25)])
        assert {e['calibration'] for e in content['data']} == set([''])


    def test_entry_list_sensor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()
        create_hourly_data_for_monitor(monitor)

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        params = {'sensor': 'b'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['sensor'] for e in content['data']} == set([params['sensor']])
        assert {e['calibration'] for e in content['data']} == set([''])

    def test_entry_list_default_sensor(self):
        '''
            Test that the entry list endpoint returns entries with the
            monitor's default sensor when no sensor is specified.
        '''
        monitor = self.get_purple_air()
        create_hourly_data_for_monitor(monitor)
        monitor.set_default_sensor(entry_models.PM25, 'b')

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }
        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        request = self.factory.get(url)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['sensor'] for e in content['data']} == set(['b'])
        assert {e['calibration'] for e in content['data']} == set([''])


    def test_entry_list_calibration(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()
        create_hourly_data_for_monitor(monitor)

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        params = {'calibration': 'EPA_PM25_Oct2021'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['sensor'] for e in content['data']} == set([monitor.get_default_sensor(entry_models.PM25)])
        assert {e['calibration'] for e in content['data']} == set([params['calibration']])
