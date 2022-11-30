from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import endpoints

from camp.apps.monitors.models import Entry
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware, parse_datetime
from camp.utils.test import debug, get_response_data

monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
entry_list = endpoints.EntryList.as_view()


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def get_purple_air(self):
        return PurpleAir.objects.get(purple_id=8892)

    def get_bam1022(self):
        return BAM1022.objects.get(name='CCAC')

    def test_monitor_detail(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        monitor = self.get_purple_air()
        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = monitor
        response = monitor_detail(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['id'] == str(monitor.pk)

    def test_monitor_list(self):
        '''
            Test that we can GET the monitor list endpoint.
        '''
        url = reverse('api:v1:monitors:monitor-list')
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_entry_list_default_sensor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()
        monitor.default_sensor = 'b'
        monitor.save()

        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        params = {'field': 'pm2'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert set(e['sensor'] for e in content['data']) == {monitor.default_sensor}

    def test_entry_list(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        params = {'sensor': 'a', 'field': 'pm2'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        sensor_count = monitor.entries.filter(sensor=params['sensor']).count()

        assert response.status_code == 200
        assert len(content['data']) == content['count'] == sensor_count
        assert set(e['sensor'] for e in content['data']) == {params['sensor']}

    def test_create_entry(self):
        '''
            Test that we can create an entry.
        '''
        monitor = self.get_bam1022()
        payload = {
            'Time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'AT(C)': '30.6',
            'RH(%)': '25.0',
            'BP(mmHg)': '764.5',
            'ConcRT(ug/m3)': '24',
        }
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['celsius'] == payload['AT(C)']
        assert content['data']['fahrenheit'] is not None

        entry = Entry.objects.latest('timestamp')
        assert entry.celsius == Decimal(payload['AT(C)'])
        assert entry.humidity == Decimal(payload['RH(%)'])

    def test_duplicate_entry(self):
        '''
            Test that duplicate entries by timestamp are not created.
        '''
        monitor = self.get_bam1022()
        payload = {
            'Time': timezone.now(),
            'AT(C)': '30.60',
            'RH(%)': '25.00',
            'BP(mmHg)': '764.5',
            'ConcRT(ug/m3)': '24',
        }

        # Create the initial entry
        entry = monitor.create_entry(payload)

        # Now call the API with the same payload and verify that it fails.
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['pm25'] == entry.pm25
        assert monitor.entries.filter(timestamp=payload['Time']).count() == 1
