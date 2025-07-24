import uuid

from resticus import http

from camp.apps.monitors.models import Monitor


class MonitorAccessMiddleware:
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
            monitor_id = view_kwargs['monitor_id']
            try:
                request.monitor = Monitor.objects.get(pk=monitor_id)
            except Monitor.DoesNotExist:
                return http.Http404(f'No monitor exists with ID "{monitor_id}".')

            # Now that we've set the monitor, we need to check for
            # appropriate authorization via the monitors access key.
            if self.authorization_required(request):
                access_key = self.get_access_key(request)
                if access_key is None:
                    return http.Http401('Access key required')

                if access_key != request.monitor.access_key:
                    return http.Http401('Invalid access key')

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
