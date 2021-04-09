import uuid

from resticus import http

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.methane.models import Methane


class MonitorAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        request.monitor = None

        # We only care about the `monitors` endpoints for now, this should be
        # refactored when `sensors` goes away. Also: account for API versions.
        if not request.path.startswith('/api/1.0/'):
            return None

        lookup = None
        if 'monitor_id' in view_kwargs:
            lookup = {'pk': view_kwargs['monitor_id']}
        elif 'methane_id' in view_kwargs:
            lookup = {
                'name': view_kwargs['methane_id'],
                'methane__isnull': False
            }

        if lookup is not None:
            try:
                request.monitor = Monitor.objects.get(**lookup)
            except Monitor.DoesNotExist:
                monitor_id = lookup.get('pk', lookup.get('name'))
                return http.Http404(f'No monitor exists with ID "{monitor_id}".')

        if self.authorization_required(request):
            access_key = self.get_access_key(request)
            if access_key is None:
                return http.Http401('Access key required')

            if access_key != request.monitor.access_key:
                return http.Http401('Invalid access key')

    def authorization_required(self, request):
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            return True

        # if request.monitor is not None:
        #     return request.monitor.is_hidden

        return False

    def get_access_key(self, request):
        access_key = request.GET.get('access_key')
        if access_key is None:
            access_key = request.headers.get('Access-Key')

        try:
            return uuid.UUID(access_key)
        except Exception as err:
            return None
