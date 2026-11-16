from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import endpoints

from camp.apps.entries import models as entry_models
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
        return PurpleAir.objects.get(sensor_id=8892)

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

    def _post_entry(self, monitor, payload):
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        return response, get_response_data(response)

    def test_create_entry(self):
        '''
            Uploads go into the entries app, not the legacy Entry table.
        '''
        monitor = self.get_bam1022()
        timestamp = timezone.now().replace(minute=0, second=0, microsecond=0)
        payload = {
            'Time': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'AT(C)': '30.6',
            'RH(%)': '25.0',
            'BP(mmHg)': '764.5',
            'ConcHR(ug/m3)': '24',
        }
        legacy_count = Entry.objects.filter(monitor=monitor).count()

        response, content = self._post_entry(monitor, payload)

        assert response.status_code == 200
        assert {e['entry_type'] for e in content['data']} == {'pm25', 'temperature', 'humidity', 'pressure'}
        assert Entry.objects.filter(monitor=monitor).count() == legacy_count

        temperature = entry_models.Temperature.objects.get(monitor=monitor, stage=entry_models.Temperature.Stage.RAW)
        assert temperature.value == Decimal('87.1')
        assert entry_models.Humidity.objects.get(monitor=monitor).value == Decimal('25.0')
        assert entry_models.PM25.objects.filter(monitor=monitor, stage=entry_models.PM25.Stage.CLEANED).exists()

    def test_duplicate_entry(self):
        '''
            Re-posting the same reading updates it in place rather than duplicating it.
        '''
        monitor = self.get_bam1022()
        payload = {
            'Time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'AT(C)': '30.60',
            'RH(%)': '25.00',
            'BP(mmHg)': '764.5',
            'ConcHR(ug/m3)': '24',
        }

        self._post_entry(monitor, payload)
        response, content = self._post_entry(monitor, {**payload, 'ConcHR(ug/m3)': '25'})

        assert response.status_code == 200
        raw = entry_models.PM25.objects.get(monitor=monitor, stage=entry_models.PM25.Stage.RAW)
        assert raw.value == Decimal('25')

    def test_create_entry_rejected_for_upload_disabled_monitor(self):
        monitor = self.get_purple_air()
        assert monitor.ENTRY_UPLOAD_ENABLED is False

        response, content = self._post_entry(monitor, {'pm25': '12.0'})

        assert response.status_code == 403


class DeprecationHeaderTests(TestCase):
    def test_v1_responses_are_marked_deprecated(self):
        response = self.client.get(reverse('api:v1:current-time'))
        assert response['Deprecation'] == 'true'
        assert 'rel="successor-version"' in response['Link']

    def test_v2_responses_are_not(self):
        response = self.client.get(reverse('api:v2:current-time'))
        assert 'Deprecation' not in response
