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

from camp.apps.emissions import areas, cepam, cities, stats
from camp.apps.emissions.models import (
    LARGE_MATURE_COWS, LARGE_OTHER_CATTLE, MEDIUM_MATURE_COWS, MEDIUM_OTHER_CATTLE,
    CountyInventory, Dairy, DairyHerd, Digester, DigesterGrant, SizeClass,
)
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.regions.models import Region

CACHE_VERSION = 6
GENERATION_KEY = 'emissions:dairies:generation'

# CARB's county inventory rows for dairy cattle waste. Silage has its own EIC
# and isn't attributed to an animal type, so it's left out.
CEPAM_SOURCE = 'LIVESTOCK HUSBANDRY'
CEPAM_SUBCATEGORY = 'DAIRY CATTLE'
CEPAM_NOTE = 'CARB county inventory, dairy cattle: animals and manure only, not feed or silage'
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
# The Dairies tab map's views ('counties' is the Areas view, its name kept
# for links) and the Areas view's levels and measures.
VIEWS = ('dairies', 'counties')
DEFAULT_VIEW = 'dairies'
AREA_LEVELS = areas.LEVELS
DEFAULT_LEVEL = Region.Type.COUNTY
MEASURES = ('mature_cows_per_sq_mi', 'mature_cows', 'dairies', 'emissions', 'emissions_per_sq_mi')
# CARB's dairy emissions estimate is by county only: no ZIP code or tract has one.
COUNTY_ONLY_MEASURES = ('emissions', 'emissions_per_sq_mi')
# Herd density by default: a count favours a big area, and CARB's county
# estimate is flat for most years (flat_since).
DEFAULT_MEASURE = 'mature_cows_per_sq_mi'
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


def city_urls():
    """
    {lowercased mailing-city name: its region page}, for linking a dairy's
    mailing city: every name cities.resolve() maps to a region with a page
    (a boundary), aliases included. Use city_url() for one city.
    """
    def compute():
        index = cities.regions_by_name()
        names = set(index) | {alias.lower() for alias in cities.CITY_ALIASES}
        urls = {}
        for name in names:
            region = cities.resolve(name, index)
            if region is not None and region.boundary_id:
                urls[name] = region.get_emissions_dairies_url()
        return urls
    return cache.get_or_set(key('city-urls'), compute, stats.CACHE_TIMEOUT)


def city_url(city):
    """The region page a dairy's mailing city links to, or None."""
    return city_urls().get(cities.lookup_key(city)) if city else None


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


def _operating_that_year():
    """The digesters operating at the outer herd's dairy in the herd's own year (Digester.operating_in, per row)."""
    return Digester.objects.filter(dairy=OuterRef('dairy')).filter(
        Q(operational_year__isnull=True) | Q(operational_year__lte=OuterRef('year')),
        Q(shutdown_year__isnull=True) | Q(shutdown_year__gt=OuterRef('year')),
    )


def narrow(queryset, *, q=None, sizes=None, digester='', **ignored):
    """
    Herds narrowed by the Dairies filter box (dairy_views.search_filters, its
    sort ignored): a name, EPA size classes (None for all) and whether the
    dairy ran a digester that year ('yes', 'no', '' for either).
    """
    if q:
        queryset = queryset.filter(dairy__name__icontains=q)
    if sizes is not None:
        queryset = queryset.filter(size_class__in=sizes)
    if digester in ('yes', 'no'):
        running = Exists(_operating_that_year())
        queryset = queryset.filter(running if digester == 'yes' else ~running)
    return queryset


def _cached(name, where, filters, compute):
    """
    `compute()` cached under `name` and `where`, and the filter box's size
    classes and digester choice; a name search runs uncached (every spelling
    would be its own entry, and narrowed that far it's quick).
    """
    filters = filters or {}
    if filters.get('q'):
        return compute()
    sizes = filters.get('sizes')
    parts = [f"sizes={','.join(sorted(sizes))}" if sizes is not None else '', f"digester={filters.get('digester') or ''}"]
    return cache.get_or_set(key(name, where, *parts), compute, stats.CACHE_TIMEOUT)


def summary(year, *, county=None, area=None, filters=None):
    """
    The year's counted dairies and how many are Large CAFOs; their milk cows,
    mature dairy cows and all cattle (mature dairy cows plus other cattle);
    how many ran a digester; milk cows as a share of all cattle and
    digesters as a share of the dairies. `filters` (the filter box's) narrows
    it, for a Dairies Summary.
    """
    def compute():
        queryset = narrow(herds(year, county=county, area=area), **(filters or {}))
        row = queryset.aggregate(
            dairies=Count('pk'), mature_cows=Sum('mature_cows'), other_cattle=Sum('other_cattle'),
            milk_cows=Sum('milk_cows'), large=Count('pk', filter=Q(size_class=SizeClass.LARGE)),
        )
        digesters = queryset.filter(Exists(_operating(year))).count() if year is not None else 0
        cattle = (row['mature_cows'] or 0) + (row['other_cattle'] or 0)
        return {
            'dairies': row['dairies'],
            'mature_cows': row['mature_cows'] or 0,
            'milk_cows': row['milk_cows'] or 0,
            'milk_share': (row['milk_cows'] or 0) / cattle if cattle else None,
            'cattle': cattle,
            'large': row['large'],
            'digesters': digesters,
            'digester_share': digesters / row['dairies'] if row['dairies'] else None,
        }
    return _cached('summary', f'{year}:{_where(county, area)}', filters, compute)


def table(year, *, county=None, area=None, q=None, sizes=None, digester='', sort=DEFAULT_SORT):
    """
    The year's counted herds with their dairies, `digester` and
    `digester_since` annotated, in a TABLE_SORTS order; narrowed to a name
    (`q`), EPA size classes (`sizes`, None for all) and digester ('yes',
    'no' or '' for either), as the map is.
    """
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
    if sizes is not None:
        queryset = queryset.filter(size_class__in=sizes)
    if digester in ('yes', 'no'):
        queryset = queryset.filter(digester=digester == 'yes')
    sort = sort if sort in TABLE_SORTS else DEFAULT_SORT
    expression = {
        'name': Lower('dairy__name'),
        'city': Lower(KeyTextTransform('city', 'dairy__address')),
        'county': F('dairy__county__name'),
        'mature_cows': F('mature_cows'),
    }[sort.lstrip('-')]
    ordered = expression.desc() if sort.startswith('-') else expression.asc()
    return queryset.order_by(ordered, Lower('dairy__name'))


def trend(*, county=None, area=None, filters=None):
    """Counted dairies, mature dairy cows and other cattle for every CADD year, under the filter box's `filters`."""
    def compute():
        queryset = narrow(DairyHerd.objects.filter(COUNTED), **(filters or {}))
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
    return _cached('trend', _where(county, area), filters, compute)


def cepam_rows(counties):
    """CARB's county inventory rows for dairy cattle (animals and manure; feed and silage left out) in `counties`, every year."""
    return CountyInventory.objects.filter(
        county__in=counties, inventory=cepam.INVENTORY, source_name=CEPAM_SOURCE, subcategory_name=CEPAM_SUBCATEGORY,
    )


def county_emissions(year, pollutant):
    """{county pk: tons/yr} of CARB's dairy cattle emissions; {} for a pollutant CARB doesn't report for them."""
    if pollutant.key not in POLLUTANT_KEYS or year is None:
        return {}

    def compute():
        rows = (
            cepam_rows(Region.objects.counties()).filter(year=year)
            .values('county').annotate(total=Sum(pollutant.key))
        )
        return {row['county']: cepam.tons_per_year(row['total']) for row in rows if row['total'] is not None}
    return cache.get_or_set(key('county-emissions', year, pollutant.key), compute, stats.CACHE_TIMEOUT)


def emissions_trend(pollutant, county=None):
    """
    CARB's dairy cattle emissions (tons/yr) for every CEPAM year in a county,
    or all the covered counties summed, with that year's all-sources total
    for the same pollutant and counties and dairy cattle's share of it; []
    for a pollutant CARB doesn't report for dairy cattle.
    """
    if pollutant.key not in POLLUTANT_KEYS:
        return []

    def compute():
        counties = [county] if county is not None else Region.objects.counties()
        field = pollutant.key
        dairy = dict(
            cepam_rows(counties).values('year').annotate(total=Sum(field)).values_list('year', 'total')
        )
        everything = dict(
            CountyInventory.objects.filter(county__in=counties, inventory=cepam.INVENTORY)
            .values('year').annotate(total=Sum(field)).values_list('year', 'total')
        )
        rows = []
        for year in sorted(dairy):
            if dairy[year] is None:
                continue
            value = cepam.tons_per_year(dairy[year])
            total = cepam.tons_per_year(everything.get(year))
            rows.append({'year': year, 'value': value, 'total': total, 'share': value / total if total else None})
        return rows
    return cache.get_or_set(key('emissions-trend', pollutant.key, county.pk if county else 'all'), compute, stats.CACHE_TIMEOUT)


def flat_since(points):
    """
    The first year from which CARB's estimate (emissions_trend rows) is the
    same every year through its last, or None when its last two years differ.
    CEPAM holds dairy cattle constant for most projection years.
    """
    rows = sorted(points, key=lambda row: row['year'])
    if len(rows) < 2:
        return None
    last = round(rows[-1]['value'], 3)
    since = rows[-1]['year']
    for row in reversed(rows[:-1]):
        if round(row['value'], 3) != last:
            break
        since = row['year']
    return since if since < rows[-1]['year'] else None


def digester_trend(*, county=None, area=None, filters=None):
    """
    For every CADD year, the counted dairies that ran a digester that year
    (Digester.operating_in: an unknown start year counts as operating),
    under the filter box's `filters`.
    """
    def compute():
        queryset = narrow(DairyHerd.objects.filter(COUNTED), **(filters or {}))
        if county is not None:
            queryset = queryset.filter(dairy__county=county)
        if area is not None:
            queryset = queryset.filter(area.dairy_q())
        rows = (
            queryset.annotate(digester=Exists(_operating_that_year()))
            .values('year').annotate(digesters=Count('pk', filter=Q(digester=True)))
            .order_by('year')
        )
        return [{'year': row['year'], 'digesters': row['digesters']} for row in rows]
    return _cached('digester-trend', _where(county, area), filters, compute)


def digester_chart_points(*, county=None, area=None, filters=None):
    """digester_trend(), or [] when no year had a digester (so there's no chart)."""
    rows = digester_trend(county=county, area=area, filters=filters)
    return rows if any(row['digesters'] for row in rows) else []


def county_values(year, pollutant):
    """Per covered county: CARB's dairy emissions (tons/yr, per sq mi) and CADD's mature dairy cows (total, per sq mi)."""
    def compute():
        miles = areas.region_sq_miles(Region.Type.COUNTY)
        emissions = county_emissions(year, pollutant)
        cows, counts = {}, {}
        for county, total, dairies in (
            herds(year).values('dairy__county').annotate(total=Sum('mature_cows'), dairies=Count('dairy', distinct=True))
            .values_list('dairy__county', 'total', 'dairies')
        ):
            cows[county], counts[county] = total, dairies
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
                'dairies': counts.get(county.pk) or 0,
            })
        return rows
    return cache.get_or_set(key('county-values', 2, year, pollutant.key), compute, stats.CACHE_TIMEOUT)


def area_values(year, pollutant, level):
    """
    The Areas view's rows for `level` (AREA_LEVELS): every covered county
    (county_values, with CARB's emissions), or each ZIP code or tract with a
    counted herd -- its dairies, mature dairy cows and cows per square mile,
    by where the dairy's point falls (region_index); no emissions there.
    """
    if level == Region.Type.COUNTY:
        return county_values(year, pollutant)

    def compute():
        index = region_index(level)
        cows, counts = {}, {}
        for dairy, mature in herds(year).values_list('dairy', 'mature_cows'):
            region = index.get(dairy)
            if region is None:
                continue
            cows[region] = cows.get(region, 0) + (mature or 0)
            counts[region] = counts.get(region, 0) + 1
        miles = areas.region_sq_miles(level)
        return [{
            'id': sqid, 'slug': slug, 'name': name,
            'emissions': None, 'emissions_per_sq_mi': None,
            'mature_cows': cows[pk],
            'mature_cows_per_sq_mi': areas._per(cows[pk], miles.get(pk)),
            'dairies': counts[pk],
        } for pk, sqid, slug, name in Region.objects.filter(pk__in=counts).order_by('name').values_list('pk', 'sqid', 'slug', 'name')]
    return cache.get_or_set(key('area-values', level, year), compute, stats.CACHE_TIMEOUT)


def dairy_areas(dairy):
    """
    The region pages a dairy counts in, the same rule as RegionArea.dairy_q():
    its county; the cities, urban areas and CDPs its point falls in, plus the
    city or CDP its mailing city (address['city']) resolves to (cities.resolve());
    its ZIP area and 2020 tract. Each community layer is listed as-is, so a
    town can appear as its city and its urban area; only a region reached
    twice (by point and by name) is listed once.
    """
    pks = [dairy.county_id]
    order = {region_type: index for index, region_type in enumerate(Region.COMMUNITY_TYPES)}
    communities = list(Region.objects.filter(
        type__in=Region.COMMUNITY_TYPES, boundary__isnull=False, boundary__geometry__intersects=dairy.point,
    ))
    named = cities.resolve(dairy.address.get('city', ''), cities.regions_by_name())
    if named is not None and named.boundary_id:
        communities.append(named)
    for region in sorted(communities, key=lambda region: (order[region.type], region.pk)):
        if region.pk not in pks:
            pks.append(region.pk)
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


def grant_totals(county):
    """
    {'grants', 'amount', 'reduction'} over a county's DigesterGrant rows
    (matched to `county` by CDFA's own county text, case-insensitively
    against the Region's short_name), or None with no rows. Cached under
    key('ddrdp', county.pk); import_ddrdp's clear_caches() invalidates it.
    """
    def compute():
        agg = DigesterGrant.objects.filter(county__iexact=county.short_name).aggregate(
            grants=Count('pk'), amount=Sum('grant_amount'), reduction=Sum('est_reduction_tco2e'),
        )
        if not agg['grants']:
            return None
        return {'grants': agg['grants'], 'amount': agg['amount'], 'reduction': agg['reduction']}
    return cache.get_or_set(key('ddrdp', county.pk), compute, stats.CACHE_TIMEOUT)
