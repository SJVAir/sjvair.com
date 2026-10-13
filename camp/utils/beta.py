from django.conf import settings
from waffle import flag_is_active

# The waffle flag (and the group it includes) that data migration
# pesticides/0002_beta_tools_flag creates. See settings.BETA_TOOLS_GATE.
BETA_TOOLS_FLAG = 'beta_tools'
BETA_TESTERS_GROUP = 'Beta testers'
BETA_TOOLS_PREFIX = '/tools/'


def beta_tools_enabled(request):
    """Whether this request may see the data tools under /tools/."""
    if not settings.BETA_TOOLS_GATE:
        return True
    return flag_is_active(request, BETA_TOOLS_FLAG)
