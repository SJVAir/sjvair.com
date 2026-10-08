"""
CalEnviroScreen figures for an area: which tracts a geometry covers and what
they add up to. Shared by the emissions explorer's region, near-me, tract and
facility pages and the admin coverage reports (reports.panels.tract_stats).

OEHHA scores census tracts and ranks them against the rest of California.
Anything here for a city, ZIP or county is SJVAir's summary of the tracts
inside it, not an OEHHA score, and the pages say so.
"""

import hashlib
from statistics import mean

from django.contrib.gis.db.models.functions import Area, Centroid, Distance, Intersection, Transform
from django.core.cache import cache
from django.db.models import Case, When

from camp.apps.ces.models import CES4, CES5
from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_CALIFORNIA_ALBERS

# OEHHA's "no score" marker in ci_score_p: tracts with too few people or
# missing indicators. They're real tracts with real populations, so they
# count toward populations and DAC figures, never toward percentile figures.
NO_SCORE = -999
# A tract belongs to a geometry when its centroid is inside it, or when the
# geometry covers at least this share of the tract's area. The centroid rule
# alone drops small places inside big rural tracts (Lost Hills, Arvin).
MIN_OVERLAP = 0.10
TOP_PERCENTILE = 75
TOP_N = 5
CACHE_VERSION = 2
CACHE_TIMEOUT = 60 * 60 * 24
# Every key includes the generation; an import bumps it (clear_caches) so a
# re-imported CES isn't served from day-old summaries. Persistent, no timeout.
GENERATION_KEY = 'ces:stats:generation'


def generation():
    return cache.get(GENERATION_KEY, 0)


def clear_caches():
    """Orphan every cached summary and tract record: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def current_model():
    """(model, tract version) for the newest CES data present: CES5, else CES4, each on its newest tract vintage; (None, None) with none loaded."""
    for model in (CES5, CES4):
        version = (
            model._base_manager.order_by('-boundary__version')
            .values_list('boundary__version', flat=True).first()
        )
        if version:
            return model, version
    return None, None


def _sq_m(value):
    """An Area annotation as square metres (a measure on PostGIS; a bare number elsewhere; None for no row)."""
    if value is None:
        return 0.0
    return float(getattr(value, 'sq_m', value))


def _score(value):
    """A percentile, or None for OEHHA's no-score marker or a null."""
    if value is None or value <= NO_SCORE:
        return None
    return float(value)


def _row(record):
    region = record.boundary.region
    return {
        'region': region,
        'number': tract_number(region),
        'ci_score_p': _score(record.ci_score_p),
        'dac': record.dac_sb535,
        'population': record.population or 0,
    }


# How far (degrees, ~10 km) to look for the nearest place when no city or
# community contains a tract's interior point.
NEAREST_PLACE_DEGREES = 0.1


def tract_place(geometry):
    """
    A short place hint for a census tract's boundary geometry ("Fresno",
    "near Easton"): the city containing its interior point, else the CDP
    containing it, else the nearest city or CDP within NEAREST_PLACE_DEGREES;
    None with nothing near. One query for the containing places (the postal
    city sorts ahead of a CDP), one more only when none contains it.
    """
    point = geometry.point_on_surface
    found = (
        Region.objects.filter(type__in=(Region.Type.CITY, Region.Type.CDP), boundary__geometry__contains=point)
        .order_by(Case(When(type=Region.Type.CITY, then=0), default=1), 'name').first()
    )
    if found is not None:
        return found.name
    nearest = (
        Region.objects.filter(
            type__in=(Region.Type.CITY, Region.Type.CDP),
            boundary__geometry__dwithin=(point, NEAREST_PLACE_DEGREES),
        )
        .annotate(distance=Distance('boundary__geometry', point))
        .order_by('distance').first()
    )
    return f'near {nearest.name}' if nearest is not None else None


def tract_number(region):
    """
    The census tract number as the Census Bureau prints it, from the 11-digit
    GEOID's last six digits: 06019002001 -> "20.01", 06019000400 -> "4". None
    when the region has no usable GEOID.
    """
    geoid = (region.external_id or '').strip()
    if len(geoid) != 11 or not geoid.isdigit():
        return None
    number, suffix = int(geoid[5:9]), geoid[9:]
    return f'{number}' if suffix == '00' else f'{number}.{suffix}'


def member_tracts(geometry, model, version):
    """The tracts `geometry` covers (see MIN_OVERLAP), as CES records with their boundary and region loaded."""
    if not geometry.valid:
        geometry = geometry.buffer(0)
    albers = geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
    candidates = (
        model.objects.filter(boundary__version=version, boundary__geometry__intersects=geometry)
        .select_related('boundary__region')
        .annotate(
            centroid=Centroid('boundary__geometry'),
            tract_sq_m=Area(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS)),
            overlap_sq_m=Area(Intersection(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS), albers)),
        )
    )
    members = []
    for record in candidates:
        tract_area = _sq_m(record.tract_sq_m)
        share = _sq_m(record.overlap_sq_m) / tract_area if tract_area else 0
        if geometry.contains(record.centroid) or share >= MIN_OVERLAP:
            members.append(record)
    return members


def _summary(geometry, model, version, places=True):
    records = member_tracts(geometry, model, version)
    rows = [_row(record) for record in records]
    shapes = {row['region'].pk: record.boundary.geometry for row, record in zip(rows, records)}
    rows.sort(key=lambda row: (row['ci_score_p'] is None, -(row['ci_score_p'] or 0)))
    scored_rows = [row for row in rows if row['ci_score_p'] is not None]
    scores = [row['ci_score_p'] for row in scored_rows]
    population = sum(row['population'] for row in rows)
    dac_population = sum(row['population'] for row in rows if row['dac'])
    containing = None
    if not rows:
        record = model.objects.filter(boundary__version=version, boundary__geometry__contains=geometry.centroid).first()
        if record is not None:
            containing = _row(record)
            shapes[containing['region'].pk] = record.boundary.geometry
    # The place hint is a spatial lookup, so only the rows a page shows get
    # one (the top tracts and the containing tract), and only for callers that
    # ask: the admin reports don't.
    if places:
        for row in [*scored_rows[:TOP_N], *([containing] if containing else [])]:
            row['place'] = tract_place(shapes[row['region'].pk])
    return {
        'model': model.__name__,
        'version': version,
        'label': str(model._meta.verbose_name),
        'tracts': rows,
        'count': len(rows),
        'scored': len(scored_rows),
        'dac_tracts': sum(1 for row in rows if row['dac']),
        'top25_tracts': sum(1 for score in scores if score >= TOP_PERCENTILE),
        'population': population,
        'dac_population': dac_population,
        'dac_share': dac_population / population if population else None,
        'min_p': min(scores) if scores else None,
        'max_p': max(scores) if scores else None,
        # Unweighted: population weighting waits for block population.
        'mean_p': mean(scores) if scores else None,
        'highest': scored_rows[0] if scored_rows else None,
        'lowest': scored_rows[-1] if scored_rows else None,
        'top': scored_rows[:TOP_N],
        'containing': containing,
    }


def tract_summary(geometry, *, model=None, places=True):
    """
    The CES tracts a geometry covers and what they add up to (see the module
    docstring for the keys), or None when no CES data is loaded. `model`
    defaults to current_model(); passing one uses its newest tract vintage.
    `places=False` skips the place hints on the rows a page names. Cached a
    day per model, vintage, geometry and `places`.
    """
    if model is None:
        model, version = current_model()
    else:
        version = (
            model._base_manager.order_by('-boundary__version')
            .values_list('boundary__version', flat=True).first()
        )
    if model is None or not version:
        return None
    digest = hashlib.md5(geometry.ewkb).hexdigest()
    key = f'ces:v{CACHE_VERSION}:g{generation()}:summary:{model.__name__}:{version}:{int(places)}:{digest}'
    return cache.get_or_set(key, lambda: _summary(geometry, model, version, places), CACHE_TIMEOUT)


def tract_record(region):
    """One tract's own row on the current model, or None for anything that isn't a scored tract region."""
    if region is None or region.type != Region.Type.TRACT or not region.boundary_id:
        return None
    model, version = current_model()
    if model is None:
        return None

    def compute():
        record = model.objects.filter(boundary_id=region.boundary_id).first()
        if record is None:
            return None
        return {
            'model': model.__name__,
            'version': version,
            'label': str(model._meta.verbose_name),
            'region': region,
            'ci_score_p': _score(record.ci_score_p),
            'pollution_p': _score(record.pollution_p),
            'popchar_p': _score(record.popchar_p),
            'dac': record.dac_sb535,
            'dac_category': str(record.get_dac_category_display()) if record.dac_category else None,
        }

    return cache.get_or_set(f'ces:v{CACHE_VERSION}:g{generation()}:tract:{model.__name__}:{region.boundary_id}', compute, CACHE_TIMEOUT)
