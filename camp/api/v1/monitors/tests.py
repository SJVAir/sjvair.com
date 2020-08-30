from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from . import endpoints

from camp.apps.monitors.models import Entry
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test import debug, get_response_data

monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
entry_list = endpoints.EntryList.as_view()


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def get_purple_air(self):
        return PurpleAir.objects.get(data__0__ID=8892)

    def get_bam1022(self):
        return BAM1022.objects.get(name='CCAC')

    def test_monitor_detail(self):
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
        url = reverse('api:v1:monitors:monitor-list')
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_entry_list(self):
        monitor = self.get_purple_air()
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        params = {'sensor': 'a', 'field': 'pm2_env'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        sensor_count = monitor.entries.filter(sensor=params['sensor']).count()

        assert response.status_code == 200
        assert len(content['data']) == content['count'] == sensor_count
        assert set(e['sensor'] for e in content['data']) == {params['sensor']}

    def test_create_entry(self):
        monitor = self.get_bam1022()
        payload = {
            'timestamp': timezone.now().isoformat(),
            'fahrenheit': '92.6',
            'pm10_env': '25',
            'pm25_env': '30',
            'pm100_env': '35',
        }
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = entry_list(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['fahrenheit'] == payload['fahrenheit']
        assert content['data']['celcius'] is not None

        entry = Entry.objects.latest('timestamp')
        assert entry.is_processed
