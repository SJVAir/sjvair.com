"""The read side of EPA ICIS-Air compliance (icis.py writes it): the facility card, the list filter and the region line."""
import time

from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Q

from camp.apps.emissions import stats
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, SourceImport

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


SOURCE = 'icis-air'
WINDOW_YEARS = 5
SHOWN_EVENTS = 25
FILTERS = ('any', 'hpv')
FILTER_LABELS = (('', 'All facilities'), ('any', 'Tracked by EPA'), ('hpv', 'With an unaddressed high-priority violation'))
TRACKED = Q(facility__icis_facilities__isnull=False)
UNADDRESSED = Q(facility__icis_facilities__current_hpv__istartswith='unaddressed')


def stamp():
    return SourceImport.latest(SOURCE)


def years_before(day, years=WINDOW_YEARS):
    """`day` minus `years` years, plus one day: the first day of a window that ends on `day`."""
    try:
        start = day.replace(year=day.year - years)
    except ValueError:  # Feb 29
        start = day.replace(year=day.year - years, day=28)
    return date.fromordinal(start.toordinal() + 1)


def filter_q(value):
    """The facility list's ?compliance= as a Q on EmissionsRecord, or None for anything else."""
    if value == 'any':
        return TRACKED
    if value == 'hpv':
        return UNADDRESSED
    return None


def facility_card(facility):
    """
    The facility page's compliance card, or None when no ICIS row matched this
    facility (nothing is shown then, by design). Every matched row's events,
    newest first; the badges from the row reported most recently; the five-year
    rollups counted back from that row's reported_through.
    """
    def compute():
        rows = list(facility.icis_facilities.all())
        if not rows:
            return None
        primary = max(rows, key=lambda row: (row.reported_through or date.min, row.pk))
        through = primary.reported_through
        since = years_before(through) if through else None
        events = list(ComplianceEvent.objects.filter(icis_facility__in=rows).order_by('-date', '-pk'))
        recent = [e for e in events if since and e.date >= since]
        return {
            'rows': rows,
            'primary': primary,
            'reported_through': through,
            'since': since,
            'inspections': sum(e.kind == ComplianceEvent.Kind.INSPECTION for e in recent),
            'novs': sum(e.kind == ComplianceEvent.Kind.NOV for e in recent),
            'formals': sum(e.kind == ComplianceEvent.Kind.FORMAL for e in recent),
            'penalties': sum((e.penalty or Decimal(0) for e in recent if e.kind == ComplianceEvent.Kind.FORMAL), Decimal(0)),
            'events': events,
            'shown': events[:SHOWN_EVENTS],
            'more': events[SHOWN_EVENTS:],
            'names': sorted({row.name for row in rows if row.name.strip().upper() != facility.name.strip().upper()}),
        }
    return cache.get_or_set(key('card', facility.pk), compute, stats.CACHE_TIMEOUT)


def area_summary(scope):
    """
    For a region or near-me page: the scope's facilities, how many have a
    matched ICIS row and how many of those carry an unaddressed HPV; None when
    none are tracked (the line isn't shown).
    """
    def compute():
        records = stats.records(scope)
        tracked = records.filter(TRACKED).values('facility_id').distinct().count()
        if not tracked:
            return None
        return {
            'facilities': stats.totals(scope)['facilities'],
            'tracked': tracked,
            'unaddressed': records.filter(UNADDRESSED).values('facility_id').distinct().count(),
        }
    # Not cache.get_or_set(): a None result (nothing tracked) is deliberately
    # never cached, so an area doesn't get stuck showing no line right after
    # an import lands rows it hasn't yet been asked about since the last
    # clear_caches(). A real result is cached as usual.
    cache_key = key('area', scope.key('compliance'))
    result = cache.get(cache_key)
    if result is not None:
        return result
    result = compute()
    if result is not None:
        cache.set(cache_key, result, stats.CACHE_TIMEOUT)
    return result
