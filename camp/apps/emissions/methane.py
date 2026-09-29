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

from camp.apps.emissions.models import Facility, MethaneSource, SourceImport

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


def attribution():
    """What every template and popup shows beside the data."""
    return {'text': MethaneSource.ATTRIBUTION, 'url': MethaneSource.HOME_URL,
            'license': MethaneSource.LICENSE, 'license_url': MethaneSource.LICENSE_URL}


def sources():
    return MethaneSource.objects.filter(gas=MethaneSource.Gas.CH4).select_related('county', 'dairy', 'facility')


def feature(source):
    return {
        'type': 'Feature',
        'id': source.sqid,
        'geometry': {'type': 'Point', 'coordinates': [round(source.point.x, 5), round(source.point.y, 5)]},
        'properties': {
            'id': source.sqid, 'name': source.source_name, 'group': source.group, 'sector': source.sector_label,
            'rate': source.emission_kg_h, 'unc': source.uncertainty_kg_h, 'rate_text': source.rate_text,
            'persistence': source.persistence, 'obs': source.observations, 'det': source.detections,
            'county': source.county.name,
            'dairy': {'id': source.dairy.sqid, 'name': source.dairy.name} if source.dairy else None,
            'facility': {'id': source.facility.sqid, 'name': source.facility.name, 'url': source.facility.get_absolute_url()} if source.facility else None,
            'viewer_url': source.viewer_url,
        },
    }


def collection():
    """The overlay's GeoJSON: every CH4 source, with the licence and attribution on the collection. Cached a day; an import invalidates it."""
    def compute():
        features = [feature(source) for source in sources().order_by('pk')]
        imported = stamp()
        return {
            'type': 'FeatureCollection',
            'properties': {
                'sources': len(features),
                'imported': imported.imported_at.date().isoformat() if imported else None,
                'attribution': MethaneSource.ATTRIBUTION, 'license': MethaneSource.LICENSE,
                'license_url': MethaneSource.LICENSE_URL, 'home_url': MethaneSource.HOME_URL,
            },
            'features': features,
        }
    return cache.get_or_set(key('geojson'), compute, CACHE_TIMEOUT)


def near_facility(facility):
    """
    The sources the import linked to this facility (their nearest trusted
    point within 1 km), nearest first. Empty for oil & gas permit groupings:
    their point is an office address, not the wells, so a plume "near" it
    says nothing (the sector page lists the Valley's oil & gas sources).
    """
    if facility.sector == Facility.Sector.OIL_GAS:
        return []
    return cache.get_or_set(
        key('facility', facility.pk),
        lambda: list(sources().filter(facility=facility).order_by('distance_m', 'pk')),
        CACHE_TIMEOUT,
    )


def for_dairy(dairy):
    return list(sources().filter(dairy=dairy))


def oil_gas_sources():
    """Every oil & gas source, by county then rate, with its facility where the import matched one."""
    def compute():
        codes = [code for code, (group, label) in MethaneSource.SECTORS.items() if group == MethaneSource.Group.OIL_GAS]
        rows = []
        for source in sources():
            if any(source.ipcc_sector.startswith(code) for code in codes):
                rows.append({'source': source, 'county': source.county, 'facility': source.facility})
        rows.sort(key=lambda r: (r['county'].name, -(r['source'].emission_kg_h or 0), r['source'].source_name))
        return rows
    return cache.get_or_set(key('oil-gas'), compute, CACHE_TIMEOUT)
