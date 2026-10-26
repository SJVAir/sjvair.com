from django.conf import settings
from django.http import Http404
from django.utils import timezone

from camp.utils.beta import beta_tools_enabled, is_beta_path


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate(settings.DEFAULT_TIMEZONE)
        return self.get_response(request)

class BetaToolsMiddleware:
    """The beta pages (/tools/, /workspace) are a 404 for anyone without the flag (see utils.beta)."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_beta_path(request.path) and not beta_tools_enabled(request):
            raise Http404()
        return self.get_response(request)
