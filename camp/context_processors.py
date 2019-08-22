from django.conf import settings
from django.views.debug import get_safe_settings


def settings_context(request):
    safe_settings = get_safe_settings()
    safe_settings['GOOGLE_MAPS_API_KEY'] = settings.GOOGLE_MAPS_API_KEY
    return {'settings': safe_settings}
