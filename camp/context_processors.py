from django.conf import settings
from django.views.debug import SafeExceptionReporterFilter

from camp.utils.beta import beta_tools_enabled


def settings_context(request):
    safe_settings = SafeExceptionReporterFilter().get_safe_settings()
    safe_settings['GOOGLE_MAPS_API_KEY'] = settings.GOOGLE_MAPS_API_KEY
    return {'settings': safe_settings}


def beta_tools(request):
    # A callable, so the flag is only checked on pages that ask (the nav).
    return {'beta_tools': lambda: beta_tools_enabled(request)}
