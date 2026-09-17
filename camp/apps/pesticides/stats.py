"""
Aggregate helpers for the pesticides explorer. Every function takes an
already-filtered queryset so the same code serves chemical, product, and
commodity pages. Aggregates run over PesticideUseRollup, the per-section,
per-month rollup of PesticideUse rebuilt by camp.apps.pesticides.rollup.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Count, F, Max, Min, Q, Sum
from django.utils import timezone

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseRollup, Product
from camp.apps.pesticides.townships import township_index
from camp.apps.regions.models import Region

LATEST_YEAR_KEY = 'pesticides:latest-year'
# Bumped whenever the cached shape changes -- v2 added `county_sqid` to
# by_county() rows, so a landing-stats entry cached under the old key would
# be missing it.
LANDING_KEY = 'pesticides:landing-stats:v2'
NOTICE_WINDOW_KEY = 'pesticides:notice-window'
YEARS_KEY = 'pesticides:years'
LATEST_YEAR_TTL = 60 * 60
LANDING_TTL = 60 * 60 * 24
NOTICE_WINDOW_TTL = 60 * 60
SJV_COUNTY_COUNT = 8
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


def year_query(year):
    """Query string that pins links to a non-default year ('' for the latest)."""
    if year is None or year == latest_year():
        return ''
    return f'?year={year}'


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


def by_county(rows, year, lbs_field='lbs_chemical'):
    counties = list(
        rows.filter(year=year)
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


def by_month(rows, year, lbs_field='lbs_chemical'):
    """
    Twelve entries, one per month, zero-filled. Month 0 (undated) is folded
    into the totals elsewhere, not shown here.
    """
    found = {
        row['month']: row
        for row in rows.filter(year=year, month__gte=1).values('month').annotate(**_totals(lbs_field))
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


def by_township(rows, year):
    """
    {township: {'lbs_chemical', 'lbs_product', 'acres_treated', 'applications'}}.

    One section-level group-by, folded into townships through the cached
    section -> township index, so the number of queries doesn't grow with the
    number of townships on screen. Both pound columns are summed because the
    map lets the viewer switch metrics without refetching.
    """
    if year is None:
        return {}
    index = township_index()
    totals = {}
    section_rows = (
        rows.filter(year=year, mtrs__isnull=False)
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


def year_totals(rows, year, lbs_field='lbs_chemical'):
    data = rows.filter(year=year).aggregate(
        lbs=Sum(lbs_field),
        applications=Sum('applications'),
        counties=Count('county', distinct=True),
    )
    return {
        'lbs': data['lbs'] or 0,
        'applications': data['applications'] or 0,
        'counties': data['counties'] or 0,
    }


def top_related(rows, year, field, lbs_field='lbs_chemical', limit=10):
    """
    Rank the related objects on `field` ('chemical' | 'product' | 'commodity')
    by pounds in `year`. Returns SimpleNamespace(obj=<instance>, lbs=<float>).
    Two queries: the group-by, then in_bulk for the instances (needed because
    sqid is not a DB column and templates need get_absolute_url()).
    """
    if year is None:
        return []
    found = list(
        rows.filter(year=year, **{f'{field}__isnull': False})
        .values(field)
        .annotate(lbs=Sum(lbs_field))
        .order_by(F('lbs').desc(nulls_last=True), field)[:limit]
    )
    model = PesticideUseRollup._meta.get_field(field).related_model
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
    rows = (
        _upcoming(notices)
        .values('county__name')
        .annotate(count=Count('id'))
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


def _top_chemicals_of_concern(top_chemicals, year, limit=10):
    # is_of_concern is derived in Python, so filter the already-fetched top-50
    # group-by; fall back to a category/IARC-restricted query if that pass
    # comes up short (a concern chemical outside the top 50 by pounds).
    rows = [r for r in top_chemicals if r.obj.is_of_concern]
    if len(rows) < limit:
        concern = PesticideUseRollup.objects.filter(chemical__in=Chemical.objects.filter(_of_concern_query()))
        rows = top_related(concern, year, 'chemical', limit=limit)
    return rows[:limit]


def landing_key(year):
    return f'{LANDING_KEY}:{year}'


def _build_landing_stats(year):
    uses = PesticideUseRollup.objects.all()
    top_chemicals_all = top_related(uses, year, 'chemical', limit=50)
    year_uses = uses.filter(year=year) if year else uses.none()
    year_totals_ = year_uses.aggregate(
        lbs=Sum('lbs_chemical'),
        applications=Sum('applications'),
        chemicals=Count('chemical', distinct=True),
        products=Count('product', distinct=True),
        commodities=Count('commodity', distinct=True),
    )
    return {
        'year': year,
        'latest_year': latest_year(),
        'years': years_loaded(),
        # Everything below is for the selected year, so the stat row reads
        # consistently next to the year picker.
        'chemical_count': year_totals_['chemicals'] or 0,
        'product_count': year_totals_['products'] or 0,
        'commodity_count': year_totals_['commodities'] or 0,
        'applications': year_totals_['applications'] or 0,
        'total_lbs': year_totals_['lbs'] or 0,
        'active_notices': upcoming_count(PesticideNotice.objects.all()),
        'top_chemicals': top_chemicals_all[:10],
        'top_chemicals_of_concern': _top_chemicals_of_concern(top_chemicals_all, year),
        'top_commodities': top_related(uses, year, 'commodity'),
        'by_county': by_county(uses, year) if year else [],
    }


def landing_stats(year=None):
    """Landing-page numbers for `year` (default: latest), cached per year."""
    if year is None:
        year = latest_year()
    key = landing_key(year)
    data = cache.get(key)
    if data is None:
        data = _build_landing_stats(year)
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
    data = _build_landing_stats(year)
    cache.set(landing_key(year), data, LANDING_TTL)
    return data
