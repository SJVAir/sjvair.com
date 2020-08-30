import uuid

from resticus import http

from camp.apps.monitors.models import Monitor


class MonitorAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        request.monitor = None
        if 'monitor_id' in view_kwargs:
            monitor_id = view_kwargs['monitor_id']
            try:
                request.monitor = Monitor.objects.get(pk=monitor_id)
            except Monitor.DoesNotExist:
                return http.Http400(f'No monitor exists with ID "{monitor_id}".')

        if self.authorization_required(request):
            access_key = self.get_access_key(request)
            if access_key is None:
                return http.Http401('Access key required')

            if access_key != request.monitor.access_key:
                return http.Http401('Invalid access key')

    def authorization_required(self, request):
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            return True
        return request.monitor.is_hidden

    def get_access_key(self, request):
        access_key = request.GET.get('access_key')
        if access_key is None:
            access_key = request.headers.get('Access-Key')

        try:
            return uuid.UUID(access_key)
        except Exception as err:
            return None
