from django.conf import settings
from django.http import Http404
from django.utils import timezone

from camp.utils.beta import BETA_TOOLS_PREFIX, beta_tools_enabled


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate(settings.DEFAULT_TIMEZONE)
        return self.get_response(request)

class BetaToolsMiddleware:
    """The data tools under /tools/ are beta: a 404 for anyone without the flag (see utils.beta)."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(BETA_TOOLS_PREFIX) and not beta_tools_enabled(request):
            raise Http404()
        return self.get_response(request)
