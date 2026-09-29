"""The read side of EPA ICIS-Air compliance (icis.py writes it): the facility card, the list filter and the region line."""
import time

from django.core.cache import cache

from camp.apps.emissions import stats

GENERATION_KEY = 'emissions:compliance:generation'


def generation():
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached compliance aggregate: they're keyed under the generation (import_icis_air calls this)."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:compliance:v{stats.CACHE_VERSION}', generation(), *parts))
