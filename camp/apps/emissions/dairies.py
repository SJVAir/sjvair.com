"""
Dairies in the emissions explorer. (Task 2 fills in the aggregates.)

Dairy aggregates and dairy API responses are cached under a generation
number that import_cadd bumps (clear_caches), so a re-import shows at once.
"""
import time

from django.core.cache import cache

CACHE_VERSION = 1
GENERATION_KEY = 'emissions:dairies:generation'


def generation():
    """
    The current cache generation. A missing one (a cleared or evicted cache)
    starts from the clock, so it never comes back to an old one.
    """
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached dairy aggregate and API response: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:dairies:v{CACHE_VERSION}', generation(), *parts))
