from decimal import Decimal
from pprint import pprint

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
# entry_list = endpoints.EntryList.as_view()


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
