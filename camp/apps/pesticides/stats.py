"""
Aggregate helpers for the pesticides explorer. Every function takes an
already-filtered queryset so the same code serves chemical, product, and
commodity pages. Aggregates run over PesticideUseRollup, the per-section,
per-month rollup of PesticideUse rebuilt by camp.apps.pesticides.rollup.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.gis.db.models.functions import Centroid
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.db.models import Count, F, Max, Min, Q, Sum
from django.utils import timezone

from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseRollup, PesticideUseTotal, Product,
)
from camp.apps.pesticides.townships import township_index
from camp.apps.regions.models import Region

LATEST_YEAR_KEY = 'pesticides:latest-year'
# Bumped whenever the cached shape changes -- v2 added `county_sqid` to
# by_county() rows and v3 added `by_year`, so a landing-stats entry cached
# under an old key would be missing them.
LANDING_KEY = 'pesticides:landing-stats:v3'
NOTICE_WINDOW_KEY = 'pesticides:notice-window'
YEARS_KEY = 'pesticides:years'
ALL_YEARS = 'all'
# Aggregates that read more than one year of rollup rows for a whole county or
# the whole valley. They only change on import, so an hour is plenty.
ALL_YEARS_KEY = 'pesticides:all-years'
ALL_YEARS_TTL = 60 * 60
LATEST_YEAR_TTL = 60 * 60
LANDING_TTL = 60 * 60 * 24
NOTICE_WINDOW_TTL = 60 * 60
SJV_COUNTY_COUNT = 8
# The explorer's third scope control, beside year and county.
CONCERN_PARAM = 'concern'
# The "within about a mile" block: a section plus the eight around it. MTRS
# sections are roughly one mile square, so a neighbour's centroid is about a
# mile away (1.5 miles diagonally) and the next ring out is about two.
BLOCK_MILES = 1.5
BLOCK_RADIUS_M = 2414
TOWNSHIP_FIELDS = ('lbs_chemical', 'lbs_product', 'acres_treated', 'applications')
_MISSING = object()


def latest_year():
    value = cache.get(LATEST_YEAR_KEY, _MISSING)
    if value is _MISSING:
        value = PesticideUseRollup.objects.aggregate(year=Max('year'))['year']
        cache.set(LATEST_YEAR_KEY, value, LATEST_YEAR_TTL)
    return value


def years_loaded():
    data = PesticideUseRollup.objects.aggregate(first=Min('year'), last=Max('year'))
    if data['first'] is None:
        return None
    return (data['first'], data['last'])


def available_years():
    """Ascending list of years with a rollup built, cached alongside latest_year."""
    value = cache.get(YEARS_KEY, _MISSING)
    if value is _MISSING:
        value = list(PesticideUseRollup.objects.order_by('year').values_list('year', flat=True).distinct())
        cache.set(YEARS_KEY, value, LATEST_YEAR_TTL)
    return value


def resolve_year(requested):
    """
    The year a page should show: the requested one if it has data, otherwise
    the latest. None only when no data is loaded at all.
    """
    years = available_years()
    if not years:
        return None
    try:
        year = int(requested)
    except (TypeError, ValueError):
        return years[-1]
    return year if year in years else years[-1]


def resolve_year_param(requested):
    """
    `(year, all_years)` for a raw `?year=` value. `?year=all` is the only way
    to get `all_years=True`; anything else resolves to a concrete year exactly
    as `resolve_year()` does, so a missing or bogus value still lands on the
    latest loaded year.
    """
    years = available_years()
    if not years:
        return None, False
    if isinstance(requested, str) and requested.strip().lower() == ALL_YEARS:
        return None, True
    return resolve_year(requested), False


def year_label(year, all_years=False):
    """'2023', '2014–2023', or '' when nothing is loaded -- for page headings."""
    if all_years:
        years = years_loaded()
        if years is None:
            return ''
        first, last = years
        return str(first) if first == last else f'{first}–{last}'
    return str(year) if year else ''


def year_query(year, all_years=False):
    """Query string that pins links to a non-default year ('' for the latest)."""
    if all_years:
        return f'?year={ALL_YEARS}'
    if year is None or year == latest_year():
        return ''
    return f'?year={year}'


def year_param(year, all_years=False):
    """`year_query()` without the leading '?', for appending to an existing query string."""
    return year_query(year, all_years).lstrip('?')


def scope_param(year, all_years=False, county=None, concern=False):
    """
    The explorer's scope as query parameters: a non-default year, a county,
    and/or the chemicals-of-concern toggle
    ('year=2020&county=kern&concern=1'), '' when they're all the defaults.
    `county` is a Region or a slug.
    """
    parts = []
    year_part = year_param(year, all_years)
    if year_part:
        parts.append(year_part)
    slug = getattr(county, 'slug', county)
    if slug:
        parts.append(f'county={slug}')
    if concern:
        parts.append(f'{CONCERN_PARAM}=1')
    return '&'.join(parts)


def scope_query(year, all_years=False, county=None, concern=False):
    """`scope_param()` with a leading '?', for appending to a bare path ('' when nothing is pinned)."""
    param = scope_param(year, all_years, county, concern)
    return f'?{param}' if param else ''


def is_concern(value):
    """True for the explorer's `?concern=1` scope flag; anything else is off."""
    return str(value or '').strip() == '1'


def all_years_key(*parts):
    return ':'.join([ALL_YEARS_KEY, *(str(part) for part in parts)])


def cached(key, build, ttl=ALL_YEARS_TTL):
    value = cache.get(key)
    if value is None:
        value = build()
        cache.set(key, value, ttl)
    return value


def in_year(rows, year, all_years=False):
    """
    The `rows` an aggregate should run over: every year when `all_years`, the
    one year otherwise. No year at all (nothing loaded) means no rows, rather
    than silently aggregating everything.
    """
    if all_years:
        return rows
    if year is None:
        return rows.none()
    return rows.filter(year=year)


def _totals(lbs_field):
    return {
        'lbs': Sum(lbs_field),
        'acres': Sum('acres_treated'),
        'applications': Sum('applications'),
    }


def by_year(rows, lbs_field='lbs_chemical'):
    return list(
        rows.values('year')
        .annotate(**_totals(lbs_field))
        .order_by('-year')
    )


def trend_deltas(by_year, year, field='lbs'):
    """
    How the selected year compares to the year before it and to the first
    loaded year, as percentages: `{'previous': {'year', 'pct'}, 'first': {...}}`
    with None where the comparison doesn't exist (no such year) and a None
    `pct` where it can't be computed (the reference year is zero or missing).

    `by_year` is newest-first, as `by_year()` returns it. `year` of None means
    All years, where the only useful reference is the first loaded year and
    the comparison runs from the newest year.
    """
    rows = list(by_year)
    empty = {'previous': None, 'first': None}
    if not rows:
        return empty

    if year is None:
        index = 0
    else:
        index = next((i for i, row in enumerate(rows) if row['year'] == year), None)
        if index is None:
            return empty

    current = rows[index][field] or 0

    def delta(row):
        base = row[field] or 0
        pct = None if not base else (current - base) / base * 100
        return {'year': row['year'], 'pct': pct}

    # Newest-first, so the previous year is the next row down.
    previous = rows[index + 1] if (year is not None and index + 1 < len(rows)) else None
    first = rows[-1] if index != len(rows) - 1 else None
    # Don't say the same year twice when the first loaded year is the previous one.
    if first is not None and previous is not None and first['year'] == previous['year']:
        first = None
    return {
        'previous': delta(previous) if previous is not None else None,
        'first': delta(first) if first is not None else None,
    }


def by_county(rows, year, lbs_field='lbs_chemical', all_years=False):
    counties = list(
        in_year(rows, year, all_years)
        .values('county_id', 'county__name', 'county__slug')
        .annotate(**_totals(lbs_field))
        .order_by(F('lbs').desc(nulls_last=True), 'county__name')
    )
    # sqid isn't a DB column, so it can't come off the aggregate above --
    # one in_bulk() for the (at most eight) counties involved.
    regions = Region.objects.in_bulk([row['county_id'] for row in counties])
    return [
        {
            'county_id': row['county_id'],
            'county_name': row['county__name'],
            'county_slug': row['county__slug'],
            'county_sqid': regions[row['county_id']].sqid if row['county_id'] in regions else None,
            'lbs': row['lbs'],
            'acres': row['acres'],
            'applications': row['applications'],
        }
        for row in counties
    ]


def by_month(rows, year, lbs_field='lbs_chemical', all_years=False):
    """
    Twelve entries, one per month, zero-filled. Month 0 (undated) is folded
    into the totals elsewhere, not shown here.
    """
    found = {
        row['month']: row
        for row in in_year(rows, year, all_years).filter(month__gte=1).values('month').annotate(**_totals(lbs_field))
    }
    return [
        {
            'month': m,
            'lbs': (found.get(m) or {}).get('lbs') or 0,
            'acres': (found.get(m) or {}).get('acres') or 0,
            'applications': (found.get(m) or {}).get('applications') or 0,
        }
        for m in range(1, 13)
    ]


def by_section(rows, year, lbs_field='lbs_chemical'):
    return [
        {'mtrs_id': r['mtrs'], 'lbs': r['lbs'] or 0, 'acres': r['acres'] or 0, 'applications': r['applications'] or 0}
        for r in rows.filter(year=year, mtrs__isnull=False).values('mtrs').annotate(**_totals(lbs_field)).order_by(F('lbs').desc(nulls_last=True), 'mtrs')
    ]


def block_sections(point):
    """
    The 3x3 block of square-mile sections around `point`: the MTRS section it
    sits in, plus the ring of sections around that one. Returns
    (home section, [section pks]) -- (None, []) when the point isn't inside
    any surveyed section.

    Neighbours are found by centroid distance rather than by touching the
    home section's boundary: PLSS sections are surveyed, not gridded, so
    neighbouring polygons don't always share an edge cleanly, but their
    centroids are reliably ~1 mile apart and the next ring out is ~2.
    """
    # Local import: camp.api.v2.pesticides.sections imports this module.
    from camp.api.v2.pesticides.sections import radius_bbox

    home = (Region.objects
        .filter(type=Region.Type.MTRS, boundary__isnull=False, boundary__geometry__contains=point)
        .select_related('boundary')
        .first()
    )
    if home is None:
        return None, []
    centroid = home.boundary.geometry.centroid
    pks = set(Region.objects
        .filter(
            type=Region.Type.MTRS,
            boundary__isnull=False,
            # Index-friendly prefilter, same reason as places.point_area().
            boundary__geometry__bboverlaps=radius_bbox(centroid.y, centroid.x, BLOCK_MILES + 0.1),
        )
        .annotate(section_centroid=Centroid('boundary__geometry'))
        .filter(section_centroid__distance_lte=(centroid, D(m=BLOCK_RADIUS_M)))
        .values_list('pk', flat=True)
    )
    pks.add(home.pk)
    return home, sorted(pks)


def block_totals(rows, point, year, all_years=False):
    """
    Pounds and applications reported in the 3x3 block of sections around
    `point` -- "within about a mile" -- plus the section the point is in.
    """
    home, pks = block_sections(point)
    if not pks:
        return {'lbs': 0, 'applications': 0, 'section': None}
    data = in_year(rows.filter(mtrs__in=pks), year, all_years).aggregate(
        lbs=Sum('lbs_chemical'),
        applications=Sum('applications'),
    )
    return {
        'lbs': data['lbs'] or 0,
        'applications': data['applications'] or 0,
        'section': home,
    }


def by_township(rows, year, all_years=False):
    """
    {township: {'lbs_chemical', 'lbs_product', 'acres_treated', 'applications'}}.

    One section-level group-by, folded into townships through the cached
    section -> township index, so the number of queries doesn't grow with the
    number of townships on screen. Both pound columns are summed because the
    map lets the viewer switch metrics without refetching.
    """
    if year is None and not all_years:
        return {}
    index = township_index()
    totals = {}
    section_rows = (
        in_year(rows, year, all_years).filter(mtrs__isnull=False)
        .values('mtrs')
        .annotate(
            lbs_chemical=Sum('lbs_chemical'),
            lbs_product=Sum('lbs_product'),
            acres_treated=Sum('acres_treated'),
            applications=Sum('applications'),
        )
    )
    for row in section_rows:
        township = index.get(row['mtrs'])
        if township is None:
            continue
        total = totals.setdefault(township, {field: 0 for field in TOWNSHIP_FIELDS})
        for field in TOWNSHIP_FIELDS:
            total[field] += row[field] or 0
    return totals


def year_totals(rows, year, lbs_field='lbs_chemical', all_years=False):
    data = in_year(rows, year, all_years).aggregate(
        lbs=Sum(lbs_field),
        applications=Sum('applications'),
        counties=Count('county', distinct=True),
    )
    return {
        'lbs': data['lbs'] or 0,
        'applications': data['applications'] or 0,
        'counties': data['counties'] or 0,
    }


def real_chemicals(rows):
    """`rows` without CDPR's placeholder chemicals (see Chemical.PLACEHOLDER_CODES)."""
    return rows.exclude(chemical__chem_code__in=Chemical.PLACEHOLDER_CODES)


def top_related(rows, year, field, lbs_field='lbs_chemical', limit=10, all_years=False):
    """
    Rank the related objects on `field` ('chemical' | 'product' | 'commodity')
    by pounds in `year` (or across every loaded year, with `all_years`).
    Returns SimpleNamespace(obj=<instance>, lbs=<float>). Two queries: the
    group-by, then in_bulk for the instances (needed because sqid is not a DB
    column and templates need get_absolute_url()). A chemical ranking leaves
    out the placeholder chemicals.
    """
    if field == 'chemical':
        rows = real_chemicals(rows)
    found = list(
        in_year(rows, year, all_years).filter(**{f'{field}__isnull': False})
        .values(field)
        .annotate(lbs=Sum(lbs_field))
        .order_by(F('lbs').desc(nulls_last=True), field)[:limit]
    )
    model = rows.model._meta.get_field(field).related_model
    objects = model.objects.in_bulk([row[field] for row in found])
    return [
        SimpleNamespace(obj=objects[row[field]], lbs=row['lbs'] or 0)
        for row in found if row[field] in objects
    ]


def recent_uses(uses, limit=10):
    return (
        uses.select_related('county', 'product', 'chemical', 'commodity')
        .order_by(F('application_date').desc(nulls_last=True), '-pk')[:limit]
    )


# SprayDays posts a notice 24-48 hours before the scheduled application, and
# the grower then has up to four days after that date to start. A notice is
# "active" until that grace period has passed.
NOTICE_GRACE_DAYS = 4


def _upcoming(notices):
    return notices.filter(scheduled_application__gte=timezone.now() - timedelta(days=NOTICE_GRACE_DAYS))


def upcoming_notices(notices, limit=10):
    return (
        _upcoming(notices)
        .select_related('county')
        .prefetch_related('chemicals', 'products')
        .order_by('scheduled_application')[:limit]
    )


def upcoming_count(notices):
    return _upcoming(notices).count()


def upcoming_by_county(notices):
    # `notices` may already carry a join -- concern_notices() joins the
    # chemicals M2M -- so count each notice once however many rows it matched.
    rows = (
        _upcoming(notices)
        .values('county__name')
        .annotate(count=Count('id', distinct=True))
        .order_by('-count', 'county__name')
    )
    return [{'county_name': row['county__name'], 'count': row['count']} for row in rows]


def notice_window():
    value = cache.get(NOTICE_WINDOW_KEY, _MISSING)
    if value is _MISSING:
        data = PesticideNotice.objects.aggregate(
            count=Count('id'),
            first=Min('scheduled_application'),
            last=Max('scheduled_application'),
        )
        value = data if data['count'] else None
        cache.set(NOTICE_WINDOW_KEY, value, NOTICE_WINDOW_TTL)
    return value


def _of_concern_query():
    return (
        Q(categories__overlap=list(Chemical.PROP65_CATEGORIES | {Chemical.Category.TOXIC_AIR_CONTAMINANT}))
        | Q(iarc_group__in=list(Chemical.IARC_CONCERN_GROUPS))
    )


def of_concern_chemicals():
    """The chemicals the explorer's "chemicals of concern" scope keeps (see `_of_concern_query`)."""
    return Chemical.objects.filter(_of_concern_query())


def concern_rows(rows):
    """`rows` (rollup or totals rows) restricted to the chemicals of concern."""
    return rows.filter(chemical__in=of_concern_chemicals())


def concern_notices(notices):
    """`notices` restricted to those listing at least one chemical of concern."""
    return notices.filter(chemicals__in=of_concern_chemicals()).distinct()


def top_chemicals_of_concern(top_chemicals, uses, year, limit=10, all_years=False):
    """
    The heaviest chemicals of concern, for the board beside "top chemicals".
    `top_chemicals` is an already-fetched group-by (the landing and place
    pages both pull 50), so the common case costs no extra query.
    """
    # is_of_concern is derived in Python, so filter the already-fetched top-50
    # group-by; fall back to a category/IARC-restricted query if that pass
    # comes up short (a concern chemical outside the top 50 by pounds).
    rows = [r for r in top_chemicals if r.obj.is_of_concern]
    if len(rows) < limit:
        concern = uses.filter(chemical__in=of_concern_chemicals())
        rows = top_related(concern, year, 'chemical', limit=limit, all_years=all_years)
    return rows[:limit]


def county_totals(year=None, all_years=False, concern=False):
    """
    Valley-wide pounds by county. Read from PesticideUseTotal (one row per
    year/county/entity) rather than the ~800k rollup rows a single year spans,
    and restricted to the chemical rows so the product and commodity rows
    don't count the same pounds again. Cached, because the all-years pass
    reads every year at once.
    """
    rows = PesticideUseTotal.objects.filter(chemical__isnull=False)
    if concern:
        rows = concern_rows(rows)
    parts = ['county-totals', ALL_YEARS if all_years else year]
    if concern:
        parts.append(CONCERN_PARAM)
    return cached(
        all_years_key(*parts),
        lambda: by_county(rows, year, all_years=all_years),
    )


def commodity_chemical_counts(county=None, concern=False):
    """
    {commodity_id: distinct chemicals applied to it, across every loaded
    year}. One group-by over the rollup, cached -- the per-commodity
    correlated subquery the single-year list uses has no usable index without
    a year to lead with.
    """
    rows = real_chemicals(PesticideUseRollup.objects.filter(commodity__isnull=False, chemical__isnull=False))
    if county is not None:
        rows = rows.filter(county=county)
    if concern:
        rows = concern_rows(rows)
    parts = ['commodity-chemicals', county.pk if county is not None else ALL_YEARS]
    if concern:
        parts.append(CONCERN_PARAM)
    return cached(
        all_years_key(*parts),
        lambda: dict(
            rows.values('commodity')
            .annotate(n=Count('chemical', distinct=True))
            .values_list('commodity', 'n')
        ),
    )


def commodity_concern_lbs(year=None, all_years=False, county=None):
    """
    {commodity_id: pounds of chemicals of concern applied to it} in `year`
    (or across every loaded year) and `county`, when given. One group-by over
    the rollup, cached the way commodity_chemical_counts is: the per-commodity
    correlated subquery the list would otherwise run sums the concern rows for
    every commodity on the page, which takes seconds across all years.
    """
    rows = concern_rows(PesticideUseRollup.objects.filter(commodity__isnull=False))
    if county is not None:
        rows = rows.filter(county=county)
    parts = [
        'commodity-concern-lbs',
        ALL_YEARS if all_years else year,
        county.pk if county is not None else '',
    ]
    return cached(
        all_years_key(*parts),
        lambda: dict(
            in_year(rows, year, all_years)
            .values('commodity')
            .annotate(lbs=Sum('lbs_chemical'))
            .values_list('commodity', 'lbs')
        ),
    )


def landing_key(year, concern=False):
    key = f'{LANDING_KEY}:{year}'
    return f'{key}:{CONCERN_PARAM}' if concern else key


def _build_landing_stats(year, all_years=False, county=None, concern=False):
    # All years reads PesticideUseTotal instead of the rollup: the same
    # numbers out of ~200k rows rather than ~8M. Pounds and applications come
    # off the chemical rows only, since the product and commodity rows of a
    # year carry the same pounds again. The concern scope can't use it: a
    # totals row names one entity, so its product and commodity rows carry no
    # chemical to filter on, and it has to read the rollup either way.
    from_totals = all_years and not concern
    uses = PesticideUseTotal.objects.all() if from_totals else PesticideUseRollup.objects.all()
    notices = PesticideNotice.objects.all()
    # Valley-wide by year, for the trend chart: always off the totals table,
    # whichever year is selected, and off its chemical rows only so the
    # product and commodity rows don't count the same pounds again.
    totals = PesticideUseTotal.objects.filter(chemical__isnull=False)
    if county is not None:
        uses = uses.filter(county=county)
        notices = notices.filter(county=county)
        totals = totals.filter(county=county)
    if concern:
        uses = concern_rows(uses)
        notices = concern_notices(notices)
        totals = concern_rows(totals)
    top_chemicals_all = top_related(uses, year, 'chemical', limit=50, all_years=all_years)
    year_uses = in_year(uses, year, all_years)
    counts = {
        'chemicals': Count('chemical', distinct=True, filter=~Q(chemical__chem_code__in=Chemical.PLACEHOLDER_CODES)),
        'products': Count('product', distinct=True),
        'commodities': Count('commodity', distinct=True),
    }
    sums = {'lbs': Sum('lbs_chemical'), 'applications': Sum('applications')}
    if from_totals:
        year_totals_ = year_uses.aggregate(**counts)
        year_totals_ |= year_uses.filter(chemical__isnull=False).aggregate(**sums)
    else:
        year_totals_ = year_uses.aggregate(**sums, **counts)
    data = {
        'year': None if all_years else year,
        'all_years': all_years,
        'year_label': year_label(year, all_years),
        'latest_year': latest_year(),
        'years': years_loaded(),
        # Everything below is for the selected year, so the stat row reads
        # consistently next to the year picker.
        'chemical_count': year_totals_['chemicals'] or 0,
        'product_count': year_totals_['products'] or 0,
        'commodity_count': year_totals_['commodities'] or 0,
        'applications': year_totals_['applications'] or 0,
        'total_lbs': year_totals_['lbs'] or 0,
        'active_notices': upcoming_count(notices),
        'top_products': top_related(uses, year, 'product', lbs_field='lbs_product', all_years=all_years),
        'top_chemicals': top_chemicals_all[:10],
        'top_commodities': top_related(uses, year, 'commodity', all_years=all_years),
        'by_county': county_totals(year, all_years, concern) if (year or all_years) else [],
        'by_year': by_year(totals),
    }
    # Under the concern scope every leaderboard is already of concern, so
    # the dedicated one would just restate the top chemicals.
    if not concern:
        data['top_chemicals_of_concern'] = top_chemicals_of_concern(
            top_chemicals_all, uses, year, all_years=all_years,
        )
    return data


def landing_stats(year=None, all_years=False, county=None, concern=False):
    """
    Landing-page numbers for `year` (default: latest) or every loaded year,
    cached per key; scoped to `county` (a Region) and to the chemicals of
    concern when the explorer is.
    """
    if all_years:
        key = landing_key(ALL_YEARS, concern)
    else:
        if year is None:
            year = latest_year()
        key = landing_key(year, concern)
    if county is not None:
        key = f'{key}:{county.slug}'
    data = cache.get(key)
    if data is None:
        data = _build_landing_stats(year, all_years, county, concern)
        cache.set(key, data, LANDING_TTL)
    return data


def refresh_landing_stats():
    """
    Reset the cached year facts and rebuild the latest year's landing stats.
    Older years are rebuilt lazily on request; their data doesn't change.
    """
    cache.delete(LATEST_YEAR_KEY)
    cache.delete(YEARS_KEY)
    cache.delete(NOTICE_WINDOW_KEY)
    year = latest_year()
    available_years()
    notice_window()
    cache.delete(all_years_key('county-totals', ALL_YEARS))
    cache.delete(all_years_key('county-totals', year))
    all_data = _build_landing_stats(None, all_years=True)
    cache.set(landing_key(ALL_YEARS), all_data, LANDING_TTL)
    data = _build_landing_stats(year)
    cache.set(landing_key(year), data, LANDING_TTL)
    return data
