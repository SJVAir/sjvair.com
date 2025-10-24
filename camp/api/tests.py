from django.core.cache import cache
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from resticus.http import Http401

from camp.api.middleware import MonitorAccessMiddleware
from camp.api.v1.monitors import endpoints
from camp.apps.monitors.purpleair.models import PurpleAir

monitor_detail = endpoints.MonitorDetail.as_view()


class MonitorAccessMiddlewareTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.middleware = MonitorAccessMiddleware(lambda: None)
        self.monitor = PurpleAir.objects.get(sensor_id=8892)

    def test_auth_optional(self):
        self.monitor.is_hidden = False
        self.monitor.save()

        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        auth_required = self.middleware.authorization_required(request)
        assert auth_required == False

    def test_access_key_param(self):
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url, {'access_key': self.monitor.access_key})
        request.monitor = self.monitor

        access_key = self.middleware.get_access_key(request)
        assert access_key == self.monitor.access_key

    def test_access_key_header(self):
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url, HTTP_ACCESS_KEY=str(self.monitor.access_key))
        request.monitor = self.monitor

        access_key = self.middleware.get_access_key(request)
        assert access_key == self.monitor.access_key

    def test_monitor_update_access_granted(self):
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, {'name': 'test'}, HTTP_ACCESS_KEY=str(self.monitor.access_key))
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is None

    def test_monitor_update_access_denied(self):
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, {})
        request.monitor = self.monitor

        process_view = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert process_view is not None
        assert isinstance(process_view, Http401)

    def test_process_view_attaches_simple_lazy_object(self):
        """
        After process_view, `request.monitor` should be a SimpleLazyObject
        proxy, not a plain Monitor instance.
        """
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        # run through process_view without manually setting request.monitor
        rv = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        assert rv is None

        # It should be a lazy proxy
        assert isinstance(request.monitor, SimpleLazyObject)
        # And not actually resolved yet — comparing identity to self.monitor should fail
        assert request.monitor is not self.monitor

    def test_lazy_monitor_populates_cache_on_first_access(self):
        """
        Before accessing any attribute, the cache should be empty.
        On first attribute access, the Monitor should be fetched
        and written into the cache.
        """
        cache_key = f'monitor:{self.monitor.pk}'
        cache.delete(cache_key)
        assert cache.get(cache_key) is None

        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        # invoke middleware to attach the lazy proxy
        _ = self.middleware.process_view(
            request, monitor_detail, (), {'monitor_id': str(self.monitor.pk)}
        )
        lazy = request.monitor
        assert isinstance(lazy, SimpleLazyObject)

        # still no cache until we actually use it
        assert cache.get(cache_key) is None

        # trigger the lookup by accessing an attribute
        pk = lazy.pk
        assert pk == self.monitor.pk

        # now the cache should have the instance
        cached = cache.get(cache_key)
        assert isinstance(cached, PurpleAir)
        assert cached.pk == self.monitor.pk
