from django.conf import settings
from django.shortcuts import redirect


class DjangoViteDevMiddelware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DJANGO_VITE_DEV_MODE and 'worker_file' in request.GET:
            vite_host = f'{settings.DJANGO_VITE_DEV_SERVER_HOST}:{settings.DJANGO_VITE_DEV_SERVER_PORT}'
            if request.get_host() != vite_host:
                return redirect(f'{settings.DJANGO_VITE_DEV_SERVER_PROTOCOL}://{vite_host}{request.get_full_path()}')
        return self.get_response(request)
