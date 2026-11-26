from django.conf import settings
from waffle import flag_is_active

# The waffle flag (and the group it includes) that data migration
# pesticides/0002_beta_tools_flag creates. See settings.BETA_TOOLS_GATE.
BETA_TOOLS_FLAG = 'beta_tools'
BETA_TESTERS_GROUP = 'Beta testers'


# Browsers fetch a web app manifest without cookies, so gating it would 404
# it for beta testers too. It holds nothing private (name, colors, icon URLs).
UNGATED_PATHS = {'/workspace/manifest.webmanifest'}

# Data tools under /tools/ that are out of beta: open to everyone, linked in the nav for all.
PUBLIC_TOOLS_PREFIXES = ('/tools/pesticides/', '/tools/emissions/')


def is_beta_path(path):
    """
    Whether a URL path is behind the beta gate: the data tools under /tools/
    (but the public ones, PUBLIC_TOOLS_PREFIXES) and the dashboard at /workspace.
    """
    if path in UNGATED_PATHS or path.startswith(PUBLIC_TOOLS_PREFIXES):
        return False
    return path.startswith('/tools/') or path == '/workspace' or path.startswith('/workspace/')


def beta_tools_enabled(request):
    """Whether this request may see the beta pages (see is_beta_path)."""
    if not settings.BETA_TOOLS_GATE:
        return True
    return flag_is_active(request, BETA_TOOLS_FLAG)
