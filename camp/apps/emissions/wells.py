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
from django.db.models import Count, Exists, F, OuterRef, Q, Sum
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
    """The wells in an area: a county by Well.county, any other region by point-in-boundary, a radius by distance."""
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    region = area.region
    if region.type == Region.Type.COUNTY:
        return Q(county=region)
    return Q(point__intersects=region.boundary.geometry)


def location_q(area):
    """The schools and child-care centers (regions.Location) in an area, by point."""
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    return Q(point__intersects=area.region.boundary.geometry)


def area_summary(area):
    """
    Wells in the area by status, and how many CalGEM has verified as inside
    a health protection zone; None when there are none (the line is hidden).
    """
    def compute():
        row = Well.objects.filter(well_q(area)).aggregate(
            total=Count('pk'),
            active=Count('pk', filter=Q(status=Well.Status.ACTIVE)),
            idle=Count('pk', filter=Q(status=Well.Status.IDLE)),
            new=Count('pk', filter=Q(status=Well.Status.NEW)),
            hpz=Count('pk', filter=Q(in_hpz=Well.HPZ.VERIFIED)),
        )
        return row if row['total'] else None
    return cache.get_or_set(key('area', area.key), compute, stats.CACHE_TIMEOUT)


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
    {sqid, name, type_label, wells}.
    """
    def compute():
        counts = locations_near_wells()
        if not counts:
            return {'count': 0, 'top': []}
        rows = [
            {'sqid': place.sqid, 'name': place.name, 'type_label': str(Location.SHORT_TYPES[place.type]), 'wells': counts[place.pk]}
            for place in Location.objects.filter(location_q(area), pk__in=list(counts)).order_by('name')
        ]
        rows.sort(key=lambda row: (-row['wells'], row['name']))
        return {'count': len(rows), 'top': rows[:SCHOOL_TOP]}
    return cache.get_or_set(key('schools', area.key), compute, stats.CACHE_TIMEOUT)


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


def table_filters(get):
    """The wells table's filters from a query string, validated: q, status, operator, field, hpz (a flag) and sort."""
    status = get.get('status')
    sort = get.get('sort')
    return {
        'q': (get.get('q') or '').strip() or None,
        'status': status if status in Well.Status.values else None,
        'operator': (get.get('operator') or '').strip() or None,
        'field': (get.get('field') or '').strip() or None,
        'hpz': get.get('hpz') == '1',
        # Newest drilling first: about half the wells carry a spud date, and those lead.
        'sort': sort if sort in TABLE_SORTS else '-spud',
    }


def table(area, *, q=None, status=None, operator=None, field=None, hpz=False, sort='-spud'):
    """The area's wells, filtered and sorted, for the Oil & gas tab's table and CSV."""
    queryset = Well.objects.filter(well_q(area))
    if q:
        queryset = queryset.filter(Q(lease_name__icontains=q) | Q(api__icontains=q))
    if status:
        queryset = queryset.filter(status=status)
    if operator:
        queryset = queryset.filter(operator_name=operator)
    if field:
        queryset = queryset.filter(field_name=field)
    if hpz:
        queryset = queryset.filter(in_hpz=Well.HPZ.VERIFIED)
    sort = sort if sort in TABLE_SORTS else '-spud'
    fields = SORT_FIELDS[sort.lstrip('-')]
    descending = sort.startswith('-')
    order = [F(name).desc(nulls_last=True) if descending else F(name).asc(nulls_last=True) for name in fields]
    return queryset.order_by(*order, 'api')


def filter_options(area):
    """The area's operators and fields by well count ({'operators': [...], 'fields': [...]}), the most first, for the filters."""
    def compute():
        wells = Well.objects.filter(well_q(area))
        def ranked(name):
            return [row[name] for row in wells.exclude(**{name: ''}).values(name).annotate(n=Count('pk')).order_by('-n', name)[:FILTER_OPTIONS]]
        return {'operators': ranked('operator_name'), 'fields': ranked('field_name')}
    return cache.get_or_set(key('options', area.key), compute, stats.CACHE_TIMEOUT)


def leaders(area):
    """
    The area's operators and oil fields with the most wells, ten each and the
    most first: {'operators': [{'label', 'count'}], 'fields': [...]}, for the
    Oil & gas tab's cards.
    """
    def compute():
        wells = Well.objects.filter(well_q(area))
        def ranked(name):
            rows = wells.exclude(**{name: ''}).values(name).annotate(n=Count('pk')).order_by('-n', name)[:LEADERS]
            return [{'label': row[name], 'count': row['n']} for row in rows]
        return {'operators': ranked('operator_name'), 'fields': ranked('field_name')}
    return cache.get_or_set(key('leaders', area.key), compute, stats.CACHE_TIMEOUT)


def spud_by_year(area):
    """
    The area's current wells by the year they were spudded (drilling began):
    [{'year', 'value'}]. CalGEM's list is today's snapshot, so this isn't a
    history of wells in service -- wells plugged since aren't in it -- but the
    spud year is the one date it carries for every well.
    """
    def compute():
        rows = (
            Well.objects.filter(well_q(area), spud_date__isnull=False)
            .annotate(year=ExtractYear('spud_date')).values('year').annotate(n=Count('pk')).order_by('year')
        )
        return [{'year': row['year'], 'value': row['n']} for row in rows]
    return cache.get_or_set(key('spud', area.key), compute, stats.CACHE_TIMEOUT)


def by_type(area):
    """The area's wells by well type (oil & gas, water injection, steam flood ...), the most first: [{'label', 'count'}], top 6."""
    def compute():
        rows = (
            Well.objects.filter(well_q(area)).exclude(well_type_label='')
            .values('well_type_label').annotate(n=Count('pk')).order_by('-n')[:6]
        )
        return [{'label': row['well_type_label'], 'count': row['n']} for row in rows]
    return cache.get_or_set(key('types', area.key), compute, stats.CACHE_TIMEOUT)
