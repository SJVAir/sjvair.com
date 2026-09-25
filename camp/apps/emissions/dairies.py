"""
Dairies in the emissions explorer.

CARB's California Dairy & Livestock Database (CADD) counts each dairy's herd
by year and lists its anaerobic digesters; CARB's county inventory (CEPAM)
estimates each county's dairy-cattle emissions. Both are shown as CARB gives
them: nothing here estimates one dairy's emissions.

A dairy counts in a year when CADD has a herd row for it that year with at
least one head of cattle counted (mature dairy cows + other cattle > 0), and
its EPA size class (models.size_class) is from that year's counts. An all-zero row is a dairy that had
closed or not yet opened: about a quarter of the Valley's rows in 2023, and
every one of them "not labeled as a dairy".

Area membership follows the facilities' rules (areas.py): counties by the
dairy's county, ZIP areas and tracts by the region its point falls in (a
cached index), every other region type by point-in-boundary.

Everything is cached a day under a generation number that import_cadd bumps
(clear_caches), so a re-import shows at once.
"""
import time

from django.core.cache import cache
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Sum
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Lower

from camp.apps.emissions import areas, cepam, stats
from camp.apps.emissions.models import (
    LARGE_MATURE_COWS, LARGE_OTHER_CATTLE, MEDIUM_MATURE_COWS, MEDIUM_OTHER_CATTLE,
    CountyInventory, Dairy, DairyHerd, Digester, SizeClass,
)
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.regions.models import Region

CACHE_VERSION = 2
GENERATION_KEY = 'emissions:dairies:generation'

# CARB's county inventory rows for dairy cattle waste. Silage has its own EIC
# and isn't attributed to an animal type, so it's left out.
CEPAM_SOURCE = 'LIVESTOCK HUSBANDRY'
CEPAM_SUBCATEGORY = 'DAIRY CATTLE'
CEPAM_NOTE = 'CARB county inventory, dairy cattle waste; silage not included'
# The explorer pollutants CARB reports for dairy cattle (its NOx, SOx and CO
# are zero; CEPAM's PM2.5 has no explorer pollutant). ROG is the fallback.
POLLUTANT_KEYS = ('rog', 'pm', 'pm10', 'tog')
DEFAULT_POLLUTANT = 'rog'
# CADD tracked fewer Valley dairies before this year (1,309, then 1,558).
COVERAGE_CHANGE_YEAR = 2019
HERD_CLASSES = (
    ('milk_cows', 'Milk cows'),
    ('dry_cows', 'Dry cows'),
    ('old_heifers', 'Heifers (older)'),
    ('young_heifers', 'Heifers (younger)'),
    ('old_calves', 'Calves (older)'),
    ('young_calves', 'Calves (younger)'),
    ('beef_cattle', 'Beef cattle'),
)
TABLE_SORTS = ('name', '-name', 'city', '-city', 'county', '-county', 'mature_cows', '-mature_cows')
DEFAULT_SORT = '-mature_cows'
TOP_ROWS = 10
# The Dairies tab map's views and its Counties measures.
VIEWS = ('dairies', 'counties')
DEFAULT_VIEW = 'dairies'
MEASURES = ('emissions', 'emissions_per_sq_mi', 'mature_cows', 'mature_cows_per_sq_mi')
DEFAULT_MEASURE = 'emissions'
# A counted herd: at least one head of cattle.
COUNTED = Q(mature_cows__gt=0) | Q(other_cattle__gt=0)
# The EPA size classes with their thresholds, largest first (the maps' legends
# and the about page).
SIZE_THRESHOLDS = {
    SizeClass.LARGE: f'{LARGE_MATURE_COWS:,} or more mature dairy cows, or {LARGE_OTHER_CATTLE:,} or more other cattle',
    SizeClass.MEDIUM: (
        f'{MEDIUM_MATURE_COWS:,}–{LARGE_MATURE_COWS - 1:,} mature dairy cows, '
        f'or {MEDIUM_OTHER_CATTLE:,}–{LARGE_OTHER_CATTLE - 1:,} other cattle'
    ),
    SizeClass.SMALL: f'Fewer than {MEDIUM_MATURE_COWS:,} mature dairy cows and {MEDIUM_OTHER_CATTLE:,} other cattle',
}


def size_classes():
    """[{key, label, threshold}] for each EPA size class, largest first."""
    return [
        {'key': size.value, 'label': str(size.label), 'threshold': SIZE_THRESHOLDS[size]}
        for size in (SizeClass.LARGE, SizeClass.MEDIUM, SizeClass.SMALL)
    ]


def generation():
    """
    The current cache generation. A missing one (a cleared or evicted cache)
    starts from the clock, so it never comes back to an old one.
    """
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached dairy aggregate and API response: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:dairies:v{CACHE_VERSION}', generation(), *parts))


def _where(county, area):
    return f"{county.pk if county else 'all'}:{area.key if area else 'anywhere'}"


def years():
    """The years CADD has a counted herd for, ascending."""
    def compute():
        return sorted(DairyHerd.objects.filter(COUNTED).values_list('year', flat=True).distinct())
    return cache.get_or_set(key('years'), compute, stats.CACHE_TIMEOUT)


def latest_year():
    known = years()
    return known[-1] if known else None


def coverage_span():
    """The years CADD has a counted herd for, as "2022–2023" (or a single year, or '' with none)."""
    known = years()
    if not known:
        return ''
    if known[0] == known[-1]:
        return str(known[0])
    return f'{known[0]}–{known[-1]}'


def coverage_counts():
    """(dairies counted in the year before COVERAGE_CHANGE_YEAR, dairies counted in COVERAGE_CHANGE_YEAR itself), for the about page."""
    def compute():
        counted = DairyHerd.objects.filter(COUNTED)
        before = counted.filter(year=COVERAGE_CHANGE_YEAR - 1).values('dairy_id').distinct().count()
        after = counted.filter(year=COVERAGE_CHANGE_YEAR).values('dairy_id').distinct().count()
        return before, after
    return cache.get_or_set(key('coverage-counts'), compute, stats.CACHE_TIMEOUT)


def dairy_count():
    """The number of Valley dairies CADD locates (every imported Dairy row), for the about page."""
    return cache.get_or_set(key('dairy-count'), Dairy.objects.count, stats.CACHE_TIMEOUT)


def region_index(level):
    """
    {dairy pk: region pk} for one Areas level: counties by Dairy.county, ZIP
    areas and tracts by the region the dairy's point falls in (one each, as
    areas.region_index does for facilities).
    """
    def compute():
        if level == Region.Type.COUNTY:
            return dict(Dairy.objects.values_list('pk', 'county_id'))
        containing = areas.containing_region(level)
        rows = Dairy.objects.annotate(region_pk=Subquery(containing)).values_list('pk', 'region_pk')
        return {dairy: region for dairy, region in rows if region is not None}
    return cache.get_or_set(key('region-index', level), compute, stats.CACHE_TIMEOUT)


def herds(year, *, county=None, area=None):
    """The year's counted herds, narrowed to a county and an area (areas.RegionArea / RadiusArea)."""
    if year is None:
        return DairyHerd.objects.none()
    queryset = DairyHerd.objects.filter(COUNTED, year=year)
    if county is not None:
        queryset = queryset.filter(dairy__county=county)
    if area is not None:
        queryset = queryset.filter(area.dairy_q())
    return queryset


def _operating(year):
    """The digesters operating in `year` at the outer query's dairy."""
    return Digester.objects.operating_in(year).filter(dairy=OuterRef('dairy'))


def summary(year, *, county=None, area=None):
    """The year's counted dairies, their mature dairy cows, how many are Large CAFOs, and how many ran a digester."""
    def compute():
        queryset = herds(year, county=county, area=area)
        row = queryset.aggregate(
            dairies=Count('pk'), mature_cows=Sum('mature_cows'),
            large=Count('pk', filter=Q(size_class=SizeClass.LARGE)),
        )
        return {
            'dairies': row['dairies'],
            'mature_cows': row['mature_cows'] or 0,
            'large': row['large'],
            'digesters': queryset.filter(Exists(_operating(year))).count() if year is not None else 0,
        }
    return cache.get_or_set(key('summary', year, _where(county, area)), compute, stats.CACHE_TIMEOUT)


def table(year, *, county=None, area=None, q=None, sort=DEFAULT_SORT):
    """The year's counted herds with their dairies, `digester` and `digester_since` annotated, in a TABLE_SORTS order."""
    operating = _operating(year) if year is not None else Digester.objects.none()
    queryset = (
        herds(year, county=county, area=area)
        .select_related('dairy', 'dairy__county')
        .annotate(
            digester=Exists(operating),
            digester_since=Subquery(operating.order_by('operational_year').values('operational_year')[:1]),
        )
    )
    if q:
        queryset = queryset.filter(dairy__name__icontains=q)
    sort = sort if sort in TABLE_SORTS else DEFAULT_SORT
    expression = {
        'name': Lower('dairy__name'),
        'city': Lower(KeyTextTransform('city', 'dairy__address')),
        'county': F('dairy__county__name'),
        'mature_cows': F('mature_cows'),
    }[sort.lstrip('-')]
    ordered = expression.desc() if sort.startswith('-') else expression.asc()
    return queryset.order_by(ordered, Lower('dairy__name'))


def trend(*, county=None, area=None):
    """Counted dairies, mature dairy cows and other cattle for every CADD year."""
    def compute():
        queryset = DairyHerd.objects.filter(COUNTED)
        if county is not None:
            queryset = queryset.filter(dairy__county=county)
        if area is not None:
            queryset = queryset.filter(area.dairy_q())
        rows = (
            queryset.values('year')
            .annotate(dairies=Count('pk'), mature_cows=Sum('mature_cows'), other_cattle=Sum('other_cattle'))
            .order_by('year')
        )
        return [{
            'year': row['year'],
            'dairies': row['dairies'],
            'mature_cows': row['mature_cows'] or 0,
            'other_cattle': row['other_cattle'] or 0,
        } for row in rows]
    return cache.get_or_set(key('trend', _where(county, area)), compute, stats.CACHE_TIMEOUT)


def county_emissions(year, pollutant):
    """{county pk: tons/yr} of CARB's dairy cattle emissions; {} for a pollutant CARB doesn't report for them."""
    if pollutant.key not in POLLUTANT_KEYS or year is None:
        return {}

    def compute():
        rows = (
            CountyInventory.objects
            .filter(county__in=Region.objects.counties(), year=year, inventory=cepam.INVENTORY,
                    source_name=CEPAM_SOURCE, subcategory_name=CEPAM_SUBCATEGORY)
            .values('county').annotate(total=Sum(pollutant.key))
        )
        return {row['county']: cepam.tons_per_year(row['total']) for row in rows if row['total'] is not None}
    return cache.get_or_set(key('county-emissions', year, pollutant.key), compute, stats.CACHE_TIMEOUT)


def county_values(year, pollutant):
    """Per covered county: CARB's dairy emissions (tons/yr, per sq mi) and CADD's mature dairy cows (total, per sq mi)."""
    def compute():
        miles = areas.region_sq_miles(Region.Type.COUNTY)
        emissions = county_emissions(year, pollutant)
        cows = dict(
            herds(year).values('dairy__county').annotate(total=Sum('mature_cows'))
            .values_list('dairy__county', 'total')
        )
        rows = []
        for county in Region.objects.counties().order_by('name'):
            tons = emissions.get(county.pk)
            herd = cows.get(county.pk) or 0
            rows.append({
                'id': county.sqid,
                'slug': county.slug,
                'name': county.name,
                'emissions': tons,
                'emissions_per_sq_mi': areas._per(tons, miles.get(county.pk)),
                'mature_cows': herd,
                'mature_cows_per_sq_mi': areas._per(herd, miles.get(county.pk)),
            })
        return rows
    return cache.get_or_set(key('county-values', year, pollutant.key), compute, stats.CACHE_TIMEOUT)


def dairy_areas(dairy):
    """
    The region pages a dairy counts in: its county, the CITY/PLACE regions its
    point falls in or whose name matches its mailing city (address['city']) --
    the same rule as RegionArea.dairy_q() -- its ZIP area and 2020 tract.
    """
    pks = [dairy.county_id]
    city = dairy.address.get('city', '')
    city_place = Region.objects.filter(
        Q(type__in=(Region.Type.CITY, Region.Type.PLACE)),
        Q(boundary__geometry__intersects=dairy.point) | (Q(name__iexact=city) if city else Q(pk__in=())),
    ).order_by('type', 'pk')
    # A synthetic PLACE shares its name with the CITY it was built from;
    # listing both only shows "Bakersfield, Bakersfield" (views.find_area_places drops it the same way).
    cities = {region.name for region in city_place if region.type == Region.Type.CITY}
    pks.extend(region.pk for region in city_place if not (region.type == Region.Type.PLACE and region.name in cities))
    for level in (Region.Type.ZIPCODE, Region.Type.TRACT):
        pk = region_index(level).get(dairy.pk)
        if pk:
            pks.append(pk)
    regions = Region.objects.in_bulk(pks)
    return [regions[pk] for pk in pks if pk in regions]


def resolve_scope(params):
    """
    The Dairies tab's scope from a request's GET, and a note for each value it
    had to change. A year CADD doesn't cover falls back to CADD's latest; a
    pollutant dairies don't report (NOx, SOx, CO, any toxic) to ROG; minor
    sources don't apply. A value missing from the URL falls back quietly (the
    explorer's default pollutant is NOx, which dairies don't report).
    """
    notes = []
    known = years()
    latest = known[-1] if known else None
    raw_year = (params.get('year') or '').strip()
    year = stats._int(raw_year)
    if year not in known:
        if raw_year and latest is not None:
            notes.append(f'CADD has herd data for {known[0]}–{latest}; showing {latest}.')
        year = latest
    fallback = POLLUTANTS[DEFAULT_POLLUTANT]
    raw = (params.get('pollutant') or '').strip()
    toxics = params.get('toxics') == '1'
    pollutant = POLLUTANTS[raw] if raw in POLLUTANT_KEYS and not toxics else fallback
    if toxics:
        notes.append(f'Dairies report no toxic air contaminants; showing {fallback.label}.')
    elif raw and raw not in POLLUTANT_KEYS:
        what = POLLUTANTS[raw].label if raw in POLLUTANTS else 'such pollutant'
        notes.append(f'Dairies report no {what}; showing {fallback.label}.')
    county = None
    if params.get('county'):
        county = Region.objects.counties().filter(slug=params['county']).first()
    return stats.Scope(year=year, county=county, pollutant=pollutant), notes
