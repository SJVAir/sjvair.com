"""
The read side of Carbon Mapper's methane sources (carbonmapper.py writes
them): the GeoJSON our maps draw, the facility card's rows, the oil & gas
list. Everything is cached a day under a generation number that
import_carbon_mapper bumps (clear_caches), the dairies pattern. The data is
Carbon Mapper's, under its non-commercial terms: every dict leaving this
module that reaches a page carries MethaneSource.ATTRIBUTION.
"""
import time

from django.core.cache import cache

from camp.apps.emissions.models import MethaneSource, SourceImport

SOURCE = 'carbon-mapper'
CACHE_VERSION = 1
GENERATION_KEY = 'emissions:methane:generation'
CACHE_TIMEOUT = 60 * 60 * 24


def generation():
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached methane aggregate and the GeoJSON: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:methane:v{CACHE_VERSION}', generation(), *parts))


def stamp():
    return SourceImport.latest(SOURCE)


def enabled():
    """Whether anything methane is offered: only after an import has run."""
    return stamp() is not None
