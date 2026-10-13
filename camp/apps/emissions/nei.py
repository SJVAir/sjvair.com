"""
EPA's National Emissions Inventory (NEI) at the county level, for what
CARB's own county inventory (CEPAM) doesn't publish: ammonia. Two data
summaries per NEI year, read straight out of their zips (the nonpoint CSV is
2.8 GB unpacked; nothing here writes it to disk):

- county x EPA sector, all pollutants: every county's total by sector;
- nonpoint county x SCC: the livestock-waste sector split by animal type
  (SCC level 3: "Dairy Cattle Waste", "Beef cattle waste", ...).

Only NH3 rows for the covered counties are kept. County FIPS codes join to
the county Regions' external_id (all eight). Estimates, not measurements. This is the read side (the ammonia bar and
the dairy tile); downloading and loading is importers.nei.
"""
from django.core.cache import cache
from django.db.models import Sum

from camp.apps.emissions import stats
from camp.apps.emissions.models import CountyNEI
from camp.apps.regions.models import Region

SOURCE = 'nei'
POLLUTANT = 'NH3'
# EPA's sector names as the files spell them (Step 2 checks them against the samples).
LIVESTOCK_SECTOR = 'Agriculture - Livestock Waste'
FERTILIZER_SECTOR = 'Agriculture - Fertilizer Application'
DAIRY_SUBSECTOR = 'Dairy Cattle Waste'
CACHE_TIMEOUT = stats.CACHE_TIMEOUT


PARTS = (
    ('dairy', 'Dairy cattle'),
    ('livestock', 'Other livestock'),
    ('fertilizer', 'Fertilizer'),
    ('other', 'Everything else'),
)


def latest_year():
    """The newest NEI year with rows, or None before any import."""
    def compute():
        return CountyNEI.objects.filter(pollutant=POLLUTANT).order_by('-year').values_list('year', flat=True).first()
    return cache.get_or_set(f'{stats.prefix()}:nei:latest-year', compute, CACHE_TIMEOUT)


def _sums(counties, year):
    """(total, livestock, dairy, fertilizer) tons for the counties in the NEI year; total 0 when there are no rows."""
    rows = CountyNEI.objects.filter(county__in=counties, year=year, pollutant=POLLUTANT)
    total = rows.filter(subsector='').aggregate(t=Sum('tons'))['t'] or 0.0
    livestock = rows.filter(subsector='', sector=LIVESTOCK_SECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    dairy = rows.filter(sector=LIVESTOCK_SECTOR, subsector=DAIRY_SUBSECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    fertilizer = rows.filter(subsector='', sector=FERTILIZER_SECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    return total, livestock, dairy, fertilizer


def context(scope):
    """
    The all-sources ammonia bar for a precursor scope: EPA's county totals by
    source (dairy cattle, other livestock, fertilizer, everything else) beside
    what the scope's permitted facilities reported to CARB. None for any
    other pollutant, or when NEI has no rows for the scope's counties.
    """
    if not scope.pollutant.precursor or scope.year is None:
        return None

    def compute():
        year = latest_year()
        if year is None:
            return None
        counties = [scope.county] if scope.county else list(Region.objects.counties())
        total, livestock, dairy, fertilizer = _sums(counties, year)
        if not total:
            return None
        # Dairy comes from the nonpoint file, the livestock total from the
        # sector file: two EPA products that needn't agree. Cap dairy at the
        # livestock total so the four segments always add up to it.
        dairy = min(dairy, livestock)
        tons = {'dairy': dairy, 'livestock': livestock - dairy, 'fertilizer': fertilizer, 'other': total - livestock - fertilizer}
        facilities = stats.totals(scope)['value'] or 0.0
        return {
            'year': year,
            'total': total,
            'facilities': facilities,
            'facility_share': facilities / total,
            'parts': [{'key': key, 'label': label, 'tons': tons[key], 'share': tons[key] / total} for key, label in PARTS],
            'counties': counties,
        }
    return cache.get_or_set(scope.key('nei-context'), compute, CACHE_TIMEOUT)


def dairy_tile(county):
    """EPA's dairy-cattle ammonia for a county, {tons, share (of the county's total), year}, or None without rows."""
    def compute():
        year = latest_year()
        if year is None:
            return None
        total, _, dairy, _ = _sums([county], year)
        if not total or not dairy:
            return None
        return {'tons': dairy, 'share': dairy / total, 'year': year}
    return cache.get_or_set(f'{stats.prefix()}:nei:dairy-tile:{county.pk}', compute, CACHE_TIMEOUT)
