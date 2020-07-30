from django.test import TestCase, RequestFactory
from django.urls import reverse

from . import endpoints
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test import get_response_data

monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
entry_list = endpoints.EntryList.as_view()


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.get(data__0__ID=8892)

    def test_monitor_list(self):
        url = reverse('api:v1:monitors:monitor-list')
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)

    def test_get_entry_list(self):
        url = reverse('api:v1:monitors:entry-list', kwargs={'monitor_id': self.monitor.pk})
        params = {'sensor': 'a', 'field': 'pm2_env'}
        request = self.factory.get(url, params)
        response = entry_list(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        sensor_count = self.monitor.entries.filter(sensor=params['sensor']).count()

        assert response.status_code == 200
        assert len(content['data']) == content['count'] == sensor_count
        assert set(e['sensor'] for e in content['data']) == {params['sensor']}
