"""
The read side of CalGEM's wells (wellstar.py writes them): counts by area,
the schools and child-care centers with a well within 3,200 ft, and the Kern
oil & gas callout. Everything cached a day under a generation number that
import_wells bumps (clear_caches), the dairies pattern.
"""
import math
import time

from django.contrib.gis.geos import Polygon
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import ExtractYear

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, ToxicEmission, Well
from camp.apps.regions.models import Location, Region

CACHE_VERSION = 1
GENERATION_KEY = 'emissions:wells:generation'


def generation():
    """The current cache generation; a missing one starts from the clock so it never comes back to an old one."""
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached wells aggregate and API response: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:wells:v{CACHE_VERSION}', generation(), *parts))


# SB 1137's health protection zone: 3,200 ft of a home, school, child-care
# center or other sensitive receptor (PRC 3280). The coarse box (in degrees,
# generous: 3,200 ft is 0.0088 deg of latitude) is the index prefilter; the
# exact check is a great-circle distance.
HPZ_FEET = 3200
COARSE_DEGREES = 0.012
FEET_PER_MILE = 5280
MILES_PER_DEGREE = 69.0
SCHOOL_TOP = 10
KERN_SLUG = 'kern'
BENZENE_ID = '71432'


def stamp():
    return SourceImport.latest('wellstar')


def well_q(area):
    """The wells in an area: a county by Well.county, any other region by point-in-boundary, a radius by distance; all of them for the Valley."""
    if isinstance(area, areas.ValleyArea):
        return Q()
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    region = area.region
    if region.type == Region.Type.COUNTY:
        return Q(county=region)
    return Q(point__intersects=region.boundary.geometry)


def location_q(area):
    """The schools and child-care centers (regions.Location) in an area, by point; all of them for the Valley."""
    if isinstance(area, areas.ValleyArea):
        return Q()
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    return Q(point__intersects=area.region.boundary.geometry)


def area_wells(area, filters=None):
    """The area's wells narrowed by the Oil & gas table's filters (table_filters, less sort), if any."""
    return filter_wells(Well.objects.filter(well_q(area)), **{name: value for name, value in (filters or {}).items() if name != 'sort'})


# The filters with a handful of fixed values, cached per value; free text runs uncached.
CACHED_PARAMS = {'status', 'type', 'hpz'}


def filtered_cache(name, area, filters, compute):
    """
    `compute()` cached per area and per the table's fixed-value filters
    (status, type, hpz), as area_values is; free text (a name, an operator, a
    field) runs uncached -- narrowed that far it's quick, and every spelling
    would be its own entry.
    """
    params = filter_params(filters or {})
    if params.keys() - CACHED_PARAMS:
        return compute()
    return cache.get_or_set(key(name, area.key, *(f'{param}={params[param]}' for param in sorted(params))), compute, stats.CACHE_TIMEOUT)


def area_summary(area, filters=None):
    """
    Wells in the area by status, and how many CalGEM has verified as inside
    a health protection zone; None when there are none (the line is hidden).
    `filters` (the table's) narrows it, for an Oil & gas Summary's stat row.
    """
    def compute():
        row = area_wells(area, filters).aggregate(
            total=Count('pk'),
            active=Count('pk', filter=Q(status=Well.Status.ACTIVE)),
            idle=Count('pk', filter=Q(status=Well.Status.IDLE)),
            new=Count('pk', filter=Q(status=Well.Status.NEW)),
            hpz=Count('pk', filter=Q(in_hpz=Well.HPZ.VERIFIED)),
        )
        return row if row['total'] else None
    return filtered_cache('area', area, filters, compute)


def _bbox(point, miles):
    """A degree bbox around `point`, slightly generous: the GiST prefilter before the exact distance (schools.py's pattern)."""
    dlat = miles / MILES_PER_DEGREE
    dlng = miles / (MILES_PER_DEGREE * max(math.cos(math.radians(point.y)), 0.01))
    box = Polygon.from_bbox((point.x - dlng, point.y - dlat, point.x + dlng, point.y + dlat))
    box.srid = 4326
    return box


def locations_near_wells():
    """
    {Location pk: wells within HPZ_FEET} for every school and child-care
    center in the Valley with at least one (about 90 of 2,800). Two steps:
    one query finds the candidates with a well inside a coarse degree box
    around them (the index does the work), then each candidate gets an exact
    great-circle count. Cached a day under the wells generation.
    """
    def compute():
        coarse = Well.objects.filter(point__dwithin=(OuterRef('point'), COARSE_DEGREES))
        candidates = Location.objects.annotate(near=Exists(coarse)).filter(near=True).only('pk', 'point')
        result = {}
        for place in candidates:
            point = place.point
            if point.srid is None:
                point.srid = 4326
            count = Well.objects.filter(
                point__bboverlaps=_bbox(point, HPZ_FEET / FEET_PER_MILE), point__distance_lte=(point, D(ft=HPZ_FEET)),
            ).count()
            if count:
                result[place.pk] = count
        return result
    return cache.get_or_set(key('near-schools'), compute, stats.CACHE_TIMEOUT)


def schools_near_wells(area):
    """
    The area's schools and child-care centers with a well within 3,200 ft:
    how many, and the SCHOOL_TOP with the most wells (then by name), each
    {sqid, name, display_name, type, type_label, run_by_name, run_by_url,
    lat, lng, wells, licenses} -- the shape schools.area_sites() rows carry,
    so the card can share the Schools tab's name-and-district cell
    (school-name-cell.html). One child-care center's several licenses are
    one row (Location.objects.one_per_place).
    """
    from camp.apps.regions import schools as region_schools

    def compute():
        counts = locations_near_wells()
        if not counts:
            return {'count': 0, 'top': []}
        districts = region_schools.district_urls(url_method='get_emissions_url')
        rows = [
            {
                'sqid': place.sqid, 'name': place.name, 'display_name': region_schools.display_name(place, place.name),
                'type': place.type, 'type_label': str(Location.SHORT_TYPES[place.type]),
                'lat': place.point.y, 'lng': place.point.x,
                'run_by_name': (place.metadata or {}).get('district_name') or '',
                **region_schools.district_fields(place, districts, url_method='get_emissions_url'),
                'wells': counts[place.pk], 'licenses': place.licenses,
            }
            for place in Location.objects.filter(location_q(area), pk__in=list(counts)).one_per_place()
            .select_related('school_district').order_by('name')
        ]
        rows.sort(key=lambda row: (-row['wells'], row['name']))
        return {'count': len(rows), 'top': rows[:SCHOOL_TOP]}
    return cache.get_or_set(key('schools-v4', area.key), compute, stats.CACHE_TIMEOUT)


def kern_callout(year):
    """
    What Kern's oil & gas permit groupings report to CARB in `year`, as a
    share of every Kern facility's total (minor sources included): ROG, and
    benzene from ToxicEmission. None when Kern reported no ROG that year;
    benzene_share is None when nobody reported benzene. Cached under the
    explorer generation (a CEIDARS or toxics import clears it).
    """
    def compute():
        kern = Region.objects.counties().filter(slug=KERN_SLUG).first()
        if kern is None:
            return None
        records = EmissionsRecord.objects.filter(year=year, facility__county=kern)
        rog_total = records.aggregate(t=Sum('rog'))['t']
        if not rog_total:
            return None
        oil_gas = records.filter(facility__sector=Facility.Sector.OIL_GAS)
        rog_oil = oil_gas.aggregate(t=Sum('rog'))['t'] or 0
        benzene = ToxicEmission.objects.filter(year=year, facility__county=kern, pollutant__carb_id=BENZENE_ID)
        benzene_total = benzene.aggregate(t=Sum('lbs'))['t']
        benzene_oil = benzene.filter(facility__sector=Facility.Sector.OIL_GAS).aggregate(t=Sum('lbs'))['t'] or 0
        return {
            'year': year,
            'facilities': oil_gas.values('facility_id').distinct().count(),
            'rog_share': float(rog_oil) / float(rog_total),
            'benzene_share': float(benzene_oil) / float(benzene_total) if benzene_total else None,
        }
    return cache.get_or_set(f'{stats.prefix()}:kern-oil-gas:{year}', compute, stats.CACHE_TIMEOUT)


# The Oil & gas tab's table (views.RegionOilGas): its sorts and filters.
TABLE_SORTS = ('label', '-label', 'operator', '-operator', 'field', '-field', 'status', '-status', 'spud', '-spud')
SORT_FIELDS = {'label': ('lease_name', 'well_number'), 'operator': ('operator_name',), 'field': ('field_name',), 'status': ('status',), 'spud': ('spud_date',)}
FILTER_OPTIONS = 40
LEADERS = 10


# The Type filter: CalGEM's 18 well types (well_type, its code) in four
# groups by what a well does. `other` is every code the first three don't
# list (observation, core and dry holes, water source, multi-purpose,
# stratigraphic, unknown), so a new code lands somewhere.
TYPE_GROUPS = (
    ('producing', 'Producing oil or gas', ('OG', 'DG')),
    ('injecting', 'Injecting to push oil out', ('SC', 'SF', 'WF', 'PM', 'AI')),
    ('disposal', 'Disposal & gas storage', ('WD', 'GD', 'GS', 'INJ')),
    ('other', 'Monitoring & other', None),
)
TYPE_VALUES = [value for value, label, codes in TYPE_GROUPS]
TYPE_OPTIONS = [(value, label) for value, label, codes in TYPE_GROUPS]


def _ticked(get, name, values):
    """The `values` ticked under `name` (repeated, or the map URL's comma-joined form), in their order; None when all or none are."""
    raw = get.getlist(name) if hasattr(get, 'getlist') else [get.get(name) or '']
    chosen = {value for item in raw for value in item.split(',')}
    ticked = [value for value in values if value in chosen]
    return ticked if 0 < len(ticked) < len(values) else None


def type_q(groups):
    """The wells in the type `groups` (TYPE_GROUPS values)."""
    listed = [code for value, label, codes in TYPE_GROUPS if codes for code in codes]
    q = Q(pk__in=[])
    for value, label, codes in TYPE_GROUPS:
        if value in groups:
            q |= Q(well_type__in=codes) if codes else ~Q(well_type__in=listed)
    return q


def table_filters(get):
    """
    The wells table's filters from a query string, validated: q, status and
    types (lists, from ticked boxes or the map URL's comma-joined form; None
    when all or none are ticked), operator, field, hpz (a flag) and sort.
    """
    sort = get.get('sort')
    return {
        'q': (get.get('q') or '').strip() or None,
        'status': _ticked(get, 'status', Well.Status.values),
        'types': _ticked(get, 'type', TYPE_VALUES),
        'operator': (get.get('operator') or '').strip() or None,
        'field': (get.get('field') or '').strip() or None,
        'hpz': get.get('hpz') == '1',
        # Newest drilling first: about half the wells carry a spud date, and those lead.
        'sort': sort if sort in TABLE_SORTS else '-spud',
    }


def filter_wells(queryset, *, q=None, status=None, types=None, operator=None, field=None, hpz=False):
    """`queryset` narrowed by the Oil & gas table's filters (the table, its CSV and the map's wells)."""
    if q:
        queryset = queryset.filter(Q(lease_name__icontains=q) | Q(api__icontains=q))
    if status:
        queryset = queryset.filter(status__in=status)
    if types:
        queryset = queryset.filter(type_q(types))
    if operator:
        queryset = queryset.filter(operator_name=operator)
    if field:
        queryset = queryset.filter(field_name=field)
    if hpz:
        queryset = queryset.filter(in_hpz=Well.HPZ.VERIFIED)
    return queryset


def filter_params(filters):
    """The table's filters that are set, as query parameters (sort left out): what the map's wells URL carries."""
    params = {key: filters[key] for key in ('q', 'operator', 'field') if filters.get(key)}
    if filters.get('status'):
        params['status'] = ','.join(filters['status'])
    if filters.get('types'):
        params['type'] = ','.join(filters['types'])
    if filters.get('hpz'):
        params['hpz'] = '1'
    return params


def table(area, *, q=None, status=None, types=None, operator=None, field=None, hpz=False, sort='-spud'):
    """The area's wells, filtered and sorted, for the Oil & gas tab's table and CSV."""
    queryset = filter_wells(Well.objects.filter(well_q(area)), q=q, status=status, types=types, operator=operator, field=field, hpz=hpz)
    sort = sort if sort in TABLE_SORTS else '-spud'
    fields = SORT_FIELDS[sort.lstrip('-')]
    descending = sort.startswith('-')
    order = [F(name).desc(nulls_last=True) if descending else F(name).asc(nulls_last=True) for name in fields]
    return queryset.order_by(*order, 'api')


def filter_options(area):
    """
    The area's operators and fields for the filters ({'operators': [...],
    'fields': [...]}): the FILTER_OPTIONS with the most wells, listed A to Z.
    """
    def compute():
        wells = Well.objects.filter(well_q(area))
        def listed(name):
            names = [row[name] for row in wells.exclude(**{name: ''}).values(name).annotate(n=Count('pk')).order_by('-n', name)[:FILTER_OPTIONS]]
            return sorted(names, key=str.casefold)
        return {'operators': listed('operator_name'), 'fields': listed('field_name')}
    return cache.get_or_set(key('options-az', area.key), compute, stats.CACHE_TIMEOUT)


def leaders(area, filters=None):
    """
    The area's operators and oil fields with the most wells, ten each and the
    most first: {'operators': [{'label', 'count'}], 'fields': [...]}, for the
    Oil & gas Summary's cards, under the table's `filters`.
    """
    def compute():
        wells = area_wells(area, filters)
        def ranked(name):
            rows = wells.exclude(**{name: ''}).values(name).annotate(n=Count('pk')).order_by('-n', name)[:LEADERS]
            return [{'label': row[name], 'count': row['n']} for row in rows]
        return {'operators': ranked('operator_name'), 'fields': ranked('field_name')}
    return filtered_cache('leaders', area, filters, compute)


def spud_by_year(area, filters=None):
    """
    The area's current wells by the year they were spudded (drilling began),
    under the table's `filters`: [{'year', 'value'}]. CalGEM's list is a
    current snapshot, so this isn't a history of wells in service -- wells
    plugged since aren't in it -- but the spud year is the one date it
    carries for every well.
    """
    def compute():
        rows = (
            area_wells(area, filters).filter(spud_date__isnull=False)
            .annotate(year=ExtractYear('spud_date')).values('year').annotate(n=Count('pk')).order_by('year')
        )
        return [{'year': row['year'], 'value': row['n']} for row in rows]
    return filtered_cache('spud', area, filters, compute)


def by_type(area, filters=None):
    """The area's wells by well type (oil & gas, water injection, steam flood ...) under the table's `filters`, the most first: [{'label', 'count'}], top 6."""
    def compute():
        rows = (
            area_wells(area, filters).exclude(well_type_label='')
            .values('well_type_label').annotate(n=Count('pk')).order_by('-n')[:6]
        )
        return [{'label': row['well_type_label'], 'count': row['n']} for row in rows]
    return filtered_cache('types', area, filters, compute)


# The Oil & gas map's Areas view: what it can shade each area by, and the
# measure it opens on (wells per square mile, so a big tract doesn't read as
# more than a small, dense one).
AREA_MEASURES = (('density', 'Wells per sq mi'), ('total', 'Wells'), ('active', 'Active wells'), ('hpz_share', 'Share in a health-protection zone'))
DEFAULT_AREA_MEASURE = 'density'


class _Count(Subquery):
    """A correlated COUNT(*) of `queryset`'s rows, for one value per outer row."""
    template = '(SELECT COUNT(*) FROM (%(subquery)s) _count)'
    output_field = IntegerField()


def area_values(level, filters=None):
    """
    The wells per area of `level` (areas.LEVELS) for the Areas view, under
    the table's filters (status, type, hpz; the free-text ones aren't cached):
    {'level', 'unit': 'wells', 'areas': [{id, wells, active, hpz,
    per_sq_mi, hpz_share}]}, only areas with a well. Counties by the well's
    county; ZIP codes and tracts by the area its point falls in.
    """
    filters = {key: value for key, value in (filters or {}).items() if key in ('q', 'status', 'types', 'operator', 'field', 'hpz') and value}

    def compute():
        wells = filter_wells(Well.objects.all(), **filters)
        regions = areas.level_regions(level)
        if level == Region.Type.COUNTY:
            counts = {
                row['county']: row for row in wells.exclude(county=None).values('county').annotate(
                    wells=Count('pk'), active=Count('pk', filter=Q(status=Well.Status.ACTIVE)),
                    hpz=Count('pk', filter=Q(in_hpz=Well.HPZ.VERIFIED)),
                )
            }
            rows = [(pk, sqid, counts[pk]) for pk, sqid in regions.filter(pk__in=counts).values_list('pk', 'sqid')]
        else:
            inside = wells.filter(point__intersects=OuterRef('boundary__geometry')).values('pk')
            annotated = regions.annotate(
                n_wells=_Count(inside), n_active=_Count(inside.filter(status=Well.Status.ACTIVE)),
                n_hpz=_Count(inside.filter(in_hpz=Well.HPZ.VERIFIED)),
            ).filter(n_wells__gt=0).values_list('pk', 'sqid', 'n_wells', 'n_active', 'n_hpz')
            rows = [(pk, sqid, {'wells': n, 'active': active, 'hpz': hpz}) for pk, sqid, n, active, hpz in annotated]
        miles = areas.region_sq_miles(level)
        result = [{
            'id': sqid,
            'wells': row['wells'],
            'active': row['active'],
            'hpz': row['hpz'],
            'per_sq_mi': row['wells'] / miles[pk] if miles.get(pk) else None,
            'hpz_share': row['hpz'] / row['wells'] if row['wells'] else None,
        } for pk, sqid, row in rows]
        result.sort(key=lambda area: area['id'])
        return {'level': level, 'unit': 'wells', 'areas': result}

    if filter_params(filters).keys() - CACHED_PARAMS:
        return compute()
    params = filter_params(filters)
    return cache.get_or_set(key('areas', level, *(f'{name}={params[name]}' for name in sorted(params))), compute, stats.CACHE_TIMEOUT)

