"""
The read side of Carbon Mapper's methane sources (carbonmapper.py writes
them): the GeoJSON our maps draw, the plumes behind a source, the oil &
gas counts and the Methane tab. No source is tied to a dairy or facility (see MethaneSource). Everything is cached a day under a generation number that
import_carbon_mapper bumps (clear_caches), the dairies pattern. The data is
Carbon Mapper's, under its non-commercial terms: every dict leaving this
module that reaches a page carries MethaneSource.ATTRIBUTION.
"""
import datetime
import time

from django.core.cache import cache
from django.db.models import Max, Min, Q

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


# The Methane tab (views.MethanePage / RegionMethane / NearMeMethane): every
# source in an area, narrowed by Carbon Mapper's sector groups, as a table and
# a summary. A source is shown by its own location and Carbon Mapper's sector,
# never tied to a facility, dairy, well or operator (see MethaneSource).

# The sector filter's choices: MethaneSource.Group, in this order, as the page names them.
GROUP_OPTIONS = (
    (MethaneSource.Group.OIL_GAS, 'Oil & gas'),
    (MethaneSource.Group.LIVESTOCK, 'Dairies & livestock'),
    # The name MethaneSource.SECTORS gives both waste codes, so the filter and the rows agree.
    (MethaneSource.Group.WASTE, 'Waste, water & recycling'),
    (MethaneSource.Group.OTHER, 'Other'),
)
GROUP_VALUES = [value for value, label in GROUP_OPTIONS]
TABLE_SORTS = ('rate', '-rate', 'sector', '-sector', 'county', '-county', 'seen', '-seen', 'last', '-last')
DEFAULT_SORT = '-rate'


def table_filters(get):
    """
    The Methane tab's filters from a query string, validated: `groups` (the
    ticked sector groups, from repeated ?sector= or the map URL's
    comma-joined form; None when all or none are ticked) and the table's sort.
    """
    raw = get.getlist('sector') if hasattr(get, 'getlist') else [get.get('sector') or '']
    chosen = {value for item in raw for value in item.split(',')}
    groups = [value for value in GROUP_VALUES if value in chosen]
    sort = get.get('sort')
    return {
        'groups': groups if 0 < len(groups) < len(GROUP_VALUES) else None,
        'sort': sort if sort in TABLE_SORTS else DEFAULT_SORT,
    }


def filter_params(filters):
    """The filters that are set, as the map's GeoJSON URL carries them."""
    return {'sector': ','.join(filters['groups'])} if filters.get('groups') else {}


def area_q(area):
    """The sources in an area (an areas.RegionArea, RadiusArea or ValleyArea), by point."""
    from camp.apps.emissions import areas
    if isinstance(area, areas.ValleyArea):
        return Q()
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    return Q(point__intersects=area.region.boundary.geometry)


def has_sources(area):
    """Whether the area has any CH4 source: its Methane tab shows only where it does."""
    return enabled() and sources().filter(area_q(area)).exists()


def plume_dates():
    """{source pk: {'first', 'last'}}: the dates of each source's first and newest plume. Cached under the generation."""
    def compute():
        rows = (
            MethanePlume.objects.filter(source__isnull=False).values('source')
            .annotate(first=Min('observed_at'), last=Max('observed_at'))
        )
        return {row['source']: {'first': row['first'].date(), 'last': row['last'].date()} for row in rows}
    return cache.get_or_set(key('plume-dates'), compute, CACHE_TIMEOUT)


def area_rows(area, *, groups=None, sort=DEFAULT_SORT):
    """
    The area's sources in the sector `groups` (None for all), sorted
    (TABLE_SORTS): [{'source', 'group', 'sector', 'county', 'first', 'last'}].
    A few hundred Valley-wide, so filtered and sorted here.
    """
    dates = plume_dates()
    rows = []
    for source in sources().filter(area_q(area)):
        group, sector = MethaneSource.sector_for(source.ipcc_sector)
        if groups is not None and group not in groups:
            continue
        seen = dates.get(source.pk, {})
        rows.append({'source': source, 'group': group, 'sector': sector, 'county': source.county,
                     'first': seen.get('first'), 'last': seen.get('last')})
    sort = sort if sort in TABLE_SORTS else DEFAULT_SORT
    keys = {
        'rate': lambda row: row['source'].emission_kg_h or 0,
        'sector': lambda row: row['sector'],
        'county': lambda row: row['county'].name,
        'seen': lambda row: row['source'].detections,
        'last': lambda row: row['last'] or datetime.date.min,
    }
    rows.sort(key=lambda row: row['source'].source_name)
    rows.sort(key=keys[sort.lstrip('-')], reverse=sort.startswith('-'))
    return rows


def area_summary(rows):
    """
    A Methane Summary from area_rows(): how many sources, the passes that saw
    a plume and the passes overhead, the newest plume's date, the sources by
    sector group (the most first) and the five with the highest rate.
    """
    labels = dict(GROUP_OPTIONS)
    counts = {}
    for row in rows:
        counts[row['group']] = counts.get(row['group'], 0) + 1
    dated = [row['last'] for row in rows if row['last']]
    rated = sorted((row for row in rows if row['source'].emission_kg_h is not None), key=lambda row: -row['source'].emission_kg_h)
    return {
        'sources': len(rows),
        'detections': sum(row['source'].detections for row in rows),
        'observations': sum(row['source'].observations for row in rows),
        'last': max(dated) if dated else None,
        'by_group': [
            {'group': group, 'label': labels[group], 'count': counts[group]}
            for group in GROUP_VALUES if counts.get(group)
        ],
        'largest': rated[:5],
    }
