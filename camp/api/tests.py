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
        self.monitor = PurpleAir.objects.get(data__0__ID=8892)

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

    def test_auth_required_hidden(self):
        self.monitor.is_hidden = True
        self.monitor.save()

        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        auth_required = self.middleware.authorization_required(request)
        assert auth_required == True

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

    def test_monitor_detail_access_granted(self):
        self.monitor.is_hidden = True
        self.monitor.save()

        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url, HTTP_ACCESS_KEY=str(self.monitor.access_key))
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is None

    def test_monitor_detail_access_denied(self):
        self.monitor.is_hidden = True
        self.monitor.save()

        url = reverse('api:v1:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is not None
        assert isinstance(process_view, Http401)
