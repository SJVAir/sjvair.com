"""
Cache warming for the data explorers (pesticides, emissions): render a fixed
list of pages in-process, the way a visitor would, so the cache entries they
read are already there when a visitor arrives.

An explorer's cached stats only change on an import, which bumps a version
its cache keys carry, so a page only needs rendering once per version. Each
rendered page leaves a marker under that version; a pass skips every page
already marked, so passes between imports are a handful of cache reads.
"""
import logging
import time

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import resolve

logger = logging.getLogger(__name__)


def warm_path(path):
    """
    Render `path` as an anonymous visitor would, filling its cache entries,
    and return the status code. The view is called directly, past the
    middleware -- the same as CachedEndpointMixin.prewarm_view -- so the beta
    gate never turns the warmer away.
    """
    request = RequestFactory().get(path)
    request.user = AnonymousUser()
    match = resolve(request.path_info)
    response = match.func(request, *match.args, **match.kwargs)
    if hasattr(response, 'render'):
        response.render()
    return response.status_code


def warm(paths, version, marker_key, force=False):
    """
    Render every one of `paths` not yet marked under `version` (every one,
    with `force`), marking each that renders. A page that fails is logged and
    left unmarked, so the next pass tries it again. Returns {'warmed',
    'skipped', 'failed', 'seconds'}.
    """
    started = time.monotonic()
    markers = {path: f'{marker_key}:{version}:{path}' for path in paths}
    done = {} if force else cache.get_many(list(markers.values()))
    result = {'warmed': 0, 'skipped': 0, 'failed': 0}
    for path in paths:
        if markers[path] in done:
            result['skipped'] += 1
            continue
        try:
            status = warm_path(path)
        except Exception:
            logger.exception('Warming %s failed', path)
            result['failed'] += 1
            continue
        if status != 200:
            logger.warning('Warming %s returned %s', path, status)
            result['failed'] += 1
            continue
        cache.set(markers[path], True, None)
        result['warmed'] += 1
    result['seconds'] = round(time.monotonic() - started, 1)
    return result
