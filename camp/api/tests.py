from django.test import TestCase, RequestFactory
from django.urls import reverse

from resticus.http import Http401

from camp.api.middleware import MonitorAccessMiddleware
from camp.api.v1.monitors import endpoints
from camp.apps.monitors.purpleair.models import PurpleAir

monitor_detail = endpoints.MonitorDetail.as_view()


class MonitorAccessMiddlewareTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = MonitorAccessMiddleware(lambda: None)
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_auth_optional(self):
        self.monitor.is_hidden = False
        self.monitor.save()

        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        auth_required = self.middleware.authorization_required(request)
        assert auth_required == False

    def test_access_key_param(self):
        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url, {'access_key': self.monitor.access_key})
        request.monitor = self.monitor

        access_key = self.middleware.get_access_key(request)
        assert access_key == self.monitor.access_key

    def test_access_key_header(self):
        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url, HTTP_ACCESS_KEY=str(self.monitor.access_key))
        request.monitor = self.monitor

        access_key = self.middleware.get_access_key(request)
        assert access_key == self.monitor.access_key

    def test_monitor_update_access_granted(self):
        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, {'name': 'test'}, HTTP_ACCESS_KEY=str(self.monitor.access_key))
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is None

    def test_monitor_update_access_denied(self):
        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, {})
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is not None
        assert isinstance(process_view, Http401)
