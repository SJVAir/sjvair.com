# project/silk_utils.py

import re
import random

from django.urls import NoReverseMatch


def silky_should_intercept(request):
    """
    Return True if Silk should profile this request,
    False if it should be skipped.
    """

    # Don't import silk until runtime to avoid AppRegistryNotReady exception
    from django.conf import settings
    from silk.middleware import get_fpath, config as silky_config

    # 1) Skip any ignored path
    for path in settings.SILKY_IGNORE_PATH_PATTERNS:
        if path.match(request.path):
            return False

    # 2) Delegate to Silk's existing percent‐sampling logic
    if silky_config.SILKY_INTERCEPT_PERCENT < 100:
        if random.random() > silky_config.SILKY_INTERCEPT_PERCENT / 100.0:
            return False

    # 3) Finally ensure we're not profiling Silk's own UI
    try:
        if request.path.startswith(get_fpath()):
            return False
    except NoReverseMatch:
        pass

    # 4) If we got here, profile it
    return True
