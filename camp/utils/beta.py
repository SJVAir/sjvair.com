from django.conf import settings
from waffle import flag_is_active

# The waffle flag (and the group it includes) that data migration
# pesticides/0002_beta_tools_flag creates. See settings.BETA_TOOLS_GATE.
BETA_TOOLS_FLAG = 'beta_tools'
BETA_TESTERS_GROUP = 'Beta testers'


def is_beta_path(path):
    """Whether a URL path is behind the beta gate: the data tools under /tools/ and the dashboard at /workspace."""
    return path.startswith('/tools/') or path == '/workspace' or path.startswith('/workspace/')


def beta_tools_enabled(request):
    """Whether this request may see the beta pages (see is_beta_path)."""
    if not settings.BETA_TOOLS_GATE:
        return True
    return flag_is_active(request, BETA_TOOLS_FLAG)
