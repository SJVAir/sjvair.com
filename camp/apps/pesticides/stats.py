"""
Aggregate helpers for the pesticides explorer. Every function takes an
already-filtered queryset so the same code serves chemical, product, and
commodity pages. Aggregates run live over PesticideUse (see the spec's
Performance section); if that gets slow, this module is the seam where a
summary table gets swapped in.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product

LATEST_YEAR_KEY = 'pesticides:latest-year'
LANDING_KEY = 'pesticides:landing-stats'
LATEST_YEAR_TTL = 60 * 60
LANDING_TTL = 60 * 60 * 24
SJV_COUNTY_COUNT = 8
_MISSING = object()


def latest_year():
    value = cache.get(LATEST_YEAR_KEY, _MISSING)
    if value is _MISSING:
        value = PesticideUse.objects.aggregate(year=Max('year'))['year']
        cache.set(LATEST_YEAR_KEY, value, LATEST_YEAR_TTL)
    return value


def years_loaded():
    data = PesticideUse.objects.aggregate(first=Min('year'), last=Max('year'))
    if data['first'] is None:
        return None
    return (data['first'], data['last'])


def _totals(lbs_field):
    return {
        'lbs': Sum(lbs_field),
        'acres': Sum('acres_treated'),
        'applications': Count('id'),
    }


def by_year(uses, lbs_field='lbs_chemical'):
    return list(
        uses.values('year')
        .annotate(**_totals(lbs_field))
        .order_by('-year')
    )


def by_county(uses, year, lbs_field='lbs_chemical'):
    rows = (
        uses.filter(year=year)
        .values('county_id', 'county__name', 'county__slug')
        .annotate(**_totals(lbs_field))
        .order_by('-lbs')
    )
    return [
        {
            'county_id': row['county_id'],
            'county_name': row['county__name'],
            'county_slug': row['county__slug'],
            'lbs': row['lbs'],
            'acres': row['acres'],
            'applications': row['applications'],
        }
        for row in rows
    ]


def year_totals(uses, year, lbs_field='lbs_chemical'):
    data = uses.filter(year=year).aggregate(
        lbs=Sum(lbs_field),
        applications=Count('id'),
        counties=Count('county', distinct=True),
    )
    return {
        'lbs': data['lbs'] or 0,
        'applications': data['applications'] or 0,
        'counties': data['counties'] or 0,
    }


def top_related(uses, year, field, lbs_field='lbs_chemical', limit=10):
    """
    Rank the related objects on `field` ('chemical' | 'product' | 'commodity')
    by pounds in `year`. Returns SimpleNamespace(obj=<instance>, lbs=<float>).
    Two queries: the group-by, then in_bulk for the instances (needed because
    sqid is not a DB column and templates need get_absolute_url()).
    """
    if year is None:
        return []
    rows = list(
        uses.filter(year=year, **{f'{field}__isnull': False})
        .values(field)
        .annotate(lbs=Sum(lbs_field))
        .order_by('-lbs')[:limit]
    )
    model = PesticideUse._meta.get_field(field).related_model
    objects = model.objects.in_bulk([row[field] for row in rows])
    return [
        SimpleNamespace(obj=objects[row[field]], lbs=row['lbs'] or 0)
        for row in rows if row[field] in objects
    ]


def recent_uses(uses, limit=10):
    return (
        uses.select_related('county', 'product', 'chemical', 'commodity')
        .order_by('-application_date', '-pk')[:limit]
    )


def _upcoming(notices):
    return notices.filter(scheduled_application__gte=timezone.now())


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
    data = PesticideNotice.objects.aggregate(
        count=Count('id'),
        first=Min('scheduled_application'),
        last=Max('scheduled_application'),
    )
    if not data['count']:
        return None
    return data


def _of_concern_query():
    return (
        Q(categories__overlap=list(Chemical.PROP65_CATEGORIES | {Chemical.Category.TOXIC_AIR_CONTAMINANT}))
        | Q(iarc_group__in=list(Chemical.IARC_CONCERN_GROUPS))
    )


def _top_chemicals_of_concern(year, limit=10):
    # is_of_concern is derived in Python, so over-fetch then filter; fall back
    # to a category/IARC-restricted query if the first pass comes up short.
    rows = [r for r in top_related(PesticideUse.objects.all(), year, 'chemical', limit=limit * 5) if r.obj.is_of_concern]
    if len(rows) < limit:
        concern = PesticideUse.objects.filter(chemical__in=Chemical.objects.filter(_of_concern_query()))
        rows = top_related(concern, year, 'chemical', limit=limit)
    return rows[:limit]


def _build_landing_stats():
    year = latest_year()
    uses = PesticideUse.objects.all()
    now = timezone.now()
    return {
        'latest_year': year,
        'years': years_loaded(),
        'chemical_count': Chemical.objects.count(),
        'product_count': Product.objects.count(),
        'commodity_count': Commodity.objects.count(),
        'total_lbs': (uses.filter(year=year).aggregate(lbs=Sum('lbs_chemical'))['lbs'] or 0) if year else 0,
        'upcoming_week': PesticideNotice.objects.filter(
            scheduled_application__gte=now,
            scheduled_application__lt=now + timedelta(days=7),
        ).count(),
        'top_chemicals': top_related(uses, year, 'chemical'),
        'top_chemicals_of_concern': _top_chemicals_of_concern(year),
        'top_commodities': top_related(uses, year, 'commodity'),
        'by_county': by_county(uses, year) if year else [],
    }


def landing_stats():
    data = cache.get(LANDING_KEY)
    if data is None:
        data = _build_landing_stats()
        cache.set(LANDING_KEY, data, LANDING_TTL)
    return data
