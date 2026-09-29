"""
The read side of CalGEM's wells (wellstar.py writes them): counts by area,
the schools and child-care centers with a well within 3,200 ft, and the Kern
oil & gas callout. Everything cached a day under a generation number that
import_wells bumps (clear_caches), the dairies pattern.
"""
import time

from django.core.cache import cache

CACHE_VERSION = 1
GENERATION_KEY = 'emissions:wells:generation'


def generation():
    """The current cache generation; a missing one starts from the clock so it never comes back to an old one."""
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached wells aggregate and API response: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:wells:v{CACHE_VERSION}', generation(), *parts))
