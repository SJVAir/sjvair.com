import uuid

from typing import Optional

from django.core.cache import cache
from django.http import JsonResponse
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _

from resticus import exceptions, http

from camp.apps.monitors.models import Monitor
from camp.utils.ids import is_small_uuid
from camp.utils.sentry import is_lookup_path


def not_found():
    # A plain str (not lazy): resticus wraps only str reasons in its errors shape.
    return exceptions.NotFound(_('Resource not found'))


class CoordinateQueryGuardMiddleware:
    """Refuses coordinates in the lookup's query string before anything can log or report them.

    Scout's error capture sends request.GET for any unhandled exception, so a GET with lat/lon
    must never reach the view stack. Sits right after SecurityMiddleware.
    """
    COORDINATE_PARAMS = ('lat', 'lon', 'latitude', 'longitude')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_lookup_path(request.path) and any(name in request.GET for name in self.COORDINATE_PARAMS):
            response = JsonResponse({'error': 'Send coordinates in a POST body.'}, status=400)
            response['Cache-Control'] = 'no-cache'
            return response
        return self.get_response(request)


class MonitorAccessMiddleware:
    CACHE_PREFIX = 'monitor:'
    CACHE_TIMEOUT = 60  # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        request.monitor = None

        # We only care about the `monitors` endpoints for now, this should be
        # refactored when `sensors` goes away. Also: account for API versions.
        if not request.path.startswith('/api/'):
            return None

        if 'monitor_id' in view_kwargs:
            request.monitor = self.get_lazy_monitor(view_kwargs['monitor_id'])

            # Now that we've set the monitor, we need to check for
            # appropriate authorization via the monitors access key.
            if self.authorization_required(request):
                access_key = self.get_access_key(request)
                if access_key is None:
                    return http.Http401('Access key required')

                try:
                    monitor_access_key = request.monitor.access_key
                except exceptions.NotFound as err:
                    return err.response
                if access_key != monitor_access_key:
                    return http.Http401('Invalid access key')

    def process_exception(self, request, exception):
        # A lazy lookup that fails outside resticus's dispatch (e.g. an endpoint's own
        # dispatch reading request.monitor first) still answers the JSON 404.
        if isinstance(exception, exceptions.NotFound):
            return exception.response
        return None

    def _get_monitor(self, monitor_id: str) -> Monitor:
        # Malformed and unknown ids answer the same 404, so neither reveals the id format.
        if not is_small_uuid(monitor_id):
            raise not_found()
        key = f'{self.CACHE_PREFIX}{monitor_id}'
        monitor: Optional[Monitor] = cache.get(key)
        if monitor is None:
            try:
                monitor = Monitor._default_manager.get(pk=monitor_id)
            except Monitor.DoesNotExist:
                raise not_found()
            cache.set(key, monitor, timeout=self.CACHE_TIMEOUT)
        return monitor

    def get_lazy_monitor(self, monitor_id: int) -> SimpleLazyObject:
        """
        Return a lazily-loaded Monitor proxy.
        The actual DB/cache lookup happens on first attribute access.
        """
        # bind monitor_id at definition time to avoid late-binding pitfalls
        return SimpleLazyObject(lambda monitor_id=monitor_id: self._get_monitor(monitor_id))

    def authorization_required(self, request):
        is_write_endpoint = request.method in ['POST', 'PUT', 'PATCH', 'DELETE']

        # If login is required, let it through – the endpoint will handle it.
        try:
            login_required = request.resolver_match.func.view_class.login_required
        except AttributeError:
            login_required = False

        return is_write_endpoint and not login_required

    def get_access_key(self, request):
        access_key = request.GET.get('access_key')
        if access_key is None:
            access_key = request.headers.get('Access-Key')

        try:
            return uuid.UUID(access_key)
        except Exception:
            return None
