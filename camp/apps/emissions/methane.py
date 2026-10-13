"""
The read side of Carbon Mapper's methane sources (carbonmapper.py writes
them): the GeoJSON our maps draw, the plumes behind a source, the oil &
gas list. No source is tied to a dairy or facility (see MethaneSource). Everything is cached a day under a generation number that
import_carbon_mapper bumps (clear_caches), the dairies pattern. The data is
Carbon Mapper's, under its non-commercial terms: every dict leaving this
module that reaches a page carries MethaneSource.ATTRIBUTION.
"""
import time

from django.core.cache import cache

from camp.apps.emissions.models import MethanePlume, MethaneSource, SourceImport

SOURCE = 'carbon-mapper'
CACHE_VERSION = 4  # 2: GeoJSON features carry their newest plume; 3: no dairy or facility on them; 4: sector names from SECTORS
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
    return MethaneSource.objects.filter(gas=MethaneSource.Gas.CH4).select_related('county')


def newest_plumes():
    """{source pk: its newest plume with a stored image}, one query (DISTINCT ON the source)."""
    plumes = (
        MethanePlume.objects.exclude(image='').filter(source__isnull=False)
        .order_by('source_id', '-observed_at').distinct('source_id')
    )
    return {plume.source_id: plume for plume in plumes}


def plume_summary(plume):
    """A source's newest plume for the overlay to draw: its image, box ([west, south, east, north]) and date."""
    if plume is None:
        return None
    return {
        'image_url': plume.image.url,
        'bbox': [round(v, 5) for v in plume.bounds_bbox],
        'date': plume.observed_at.date().isoformat(),
    }


def feature(source, plume=None):
    return {
        'type': 'Feature',
        'id': source.sqid,
        'geometry': {'type': 'Point', 'coordinates': [round(source.point.x, 5), round(source.point.y, 5)]},
        'properties': {
            'id': source.sqid, 'name': source.source_name, 'group': source.group, 'sector': source.sector_label,
            'rate': source.emission_kg_h, 'unc': source.uncertainty_kg_h, 'rate_text': source.rate_text,
            'persistence': source.persistence, 'obs': source.observations, 'det': source.detections,
            'county': source.county.name,
            'viewer_url': source.viewer_url,
            'plume': plume_summary(plume),
        },
    }


def collection():
    """The overlay's GeoJSON: every CH4 source. Cached a day; an import invalidates it. Attribution is on the pages and the map, not in the payload."""
    def compute():
        plumes = newest_plumes()
        features = [feature(source, plumes.get(source.pk)) for source in sources().order_by('pk')]
        imported = stamp()
        return {
            'type': 'FeatureCollection',
            'properties': {
                'sources': len(features),
                'imported': imported.imported_at.date().isoformat() if imported else None,
            },
            'features': features,
        }
    return cache.get_or_set(key('geojson'), compute, CACHE_TIMEOUT)


def plume_rate_text(plume):
    """Same format as MethaneSource.rate_text, for a plume's own estimate."""
    if plume.emission_kg_h is None:
        return 'rate not estimated'
    text = f'{plume.emission_kg_h:,.0f}'
    if plume.uncertainty_kg_h is not None:
        text += f' ± {plume.uncertainty_kg_h:,.0f}'
    return f'{text} kg/h'


def plume_data(plume):
    """One plume for the plumes API/popup stepper: rate, wind, the 4-corner
    bounds a MapLibre image source wants (top-left, top-right, bottom-right,
    bottom-left), and the stored image's URL, or None when there isn't one."""
    west, south, east, north = plume.bounds_bbox
    return {
        'id': plume.sqid,
        'observed_at': plume.observed_at.isoformat(),
        'platform': plume.platform,
        'instrument': plume.instrument,
        'rate': plume.emission_kg_h,
        'uncertainty': plume.uncertainty_kg_h,
        'rate_text': plume_rate_text(plume),
        'wind_speed': plume.wind_speed,
        'wind_direction': plume.wind_direction,
        'bounds': [[west, north], [east, north], [east, south], [west, south]],
        'image_url': plume.image.url if plume.image else None,
    }


def source_plumes(source):
    """A source's plumes, newest first, for the API/popup stepper. Cached
    under the generation; a re-import invalidates it."""
    def compute():
        plumes = [plume_data(plume) for plume in source.plumes.order_by('-observed_at')]
        return {
            'source': source.sqid,
            'plumes': plumes,
        }
    return cache.get_or_set(key('plumes', source.pk), compute, CACHE_TIMEOUT)


def oil_gas_sources():
    """Every oil & gas source (Carbon Mapper's sector), by county then rate."""
    def compute():
        codes = [code for code, (group, label) in MethaneSource.SECTORS.items() if group == MethaneSource.Group.OIL_GAS]
        rows = []
        for source in sources():
            if any(source.ipcc_sector.startswith(code) for code in codes):
                rows.append({'source': source, 'county': source.county})
        rows.sort(key=lambda r: (r['county'].name, -(r['source'].emission_kg_h or 0), r['source'].source_name))
        return rows
    return cache.get_or_set(key('oil-gas'), compute, CACHE_TIMEOUT)
