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

from django.contrib.gis.db.models.functions import Area, Centroid, Intersection, Transform
from django.core.cache import cache

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
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24


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
    return {
        'region': record.boundary.region,
        'ci_score_p': _score(record.ci_score_p),
        'dac': record.dac_sb535,
        'population': record.population or 0,
    }


def member_tracts(geometry, model, version):
    """The tracts `geometry` covers (see MIN_OVERLAP), as CES records with their boundary and region loaded."""
    if not geometry.valid:
        geometry = geometry.buffer(0)
    albers = geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
    candidates = (
        model.objects.filter(boundary__version=version, boundary__geometry__intersects=geometry)
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


def _summary(geometry, model, version):
    rows = [_row(record) for record in member_tracts(geometry, model, version)]
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


def tract_summary(geometry, *, model=None):
    """
    The CES tracts a geometry covers and what they add up to (see the module
    docstring for the keys), or None when no CES data is loaded. `model`
    defaults to current_model(); passing one uses its newest tract vintage.
    Cached a day per model, vintage and geometry.
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
    key = f'ces:v{CACHE_VERSION}:summary:{model.__name__}:{version}:{digest}'
    return cache.get_or_set(key, lambda: _summary(geometry, model, version), CACHE_TIMEOUT)


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

    return cache.get_or_set(f'ces:v{CACHE_VERSION}:tract:{model.__name__}:{region.boundary_id}', compute, CACHE_TIMEOUT)
