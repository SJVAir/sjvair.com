"""
Emissions by area.

Which ZIP area and census tract each facility's point falls in, the totals
the map's Areas view shades, and the Area objects that narrow a stats.Scope
to one region or a radius (region pages, near-me).

Counties count by CARB's county code (Facility.county); ZIP areas, tracts and
every other region type by the facility's point. Facility data is never
rewritten: the point-to-region mapping is computed and cached.
"""
import math
from dataclasses import dataclass, replace

from django.contrib.gis.db.models.functions import Area as AreaOf, Transform
from django.contrib.gis.geos import GEOSGeometry, Point, Polygon
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.db.models import OuterRef, Q, Subquery

from camp.apps.emissions import cities, stats
from camp.apps.emissions.models import Facility
from camp.apps.regions import shapes
from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_CALIFORNIA_ALBERS, EPSG_LATLON

LEVELS = (Region.Type.COUNTY, Region.Type.ZIPCODE, Region.Type.TRACT)
# Census tracts: the finest level, and the one CalEnviroScreen and the Community tab use.
DEFAULT_LEVEL = Region.Type.TRACT
MEASURES = ('density', 'total', 'per_resident')
DEFAULT_MEASURE = 'density'
# The map level a region page opens its Areas view at: tracts, like the
# Valley map. A tract page has none (it's the finest level).
NEXT_LEVEL = {
    Region.Type.COUNTY: Region.Type.TRACT,
    Region.Type.CITY: Region.Type.TRACT,
    Region.Type.URBAN_AREA: Region.Type.TRACT,
    Region.Type.CDP: Region.Type.TRACT,
    Region.Type.ZIPCODE: Region.Type.TRACT,
    Region.Type.SCHOOL_DISTRICT: Region.Type.TRACT,
    Region.Type.AB617_COMMUNITY: Region.Type.TRACT,
}
SQ_METERS_PER_SQ_MILE = 2_589_988.110336
MILES_PER_DEGREE = 69.0
METERS_PER_MILE = 1609.344


def _key(name, *parts):
    return ':'.join(str(part) for part in (stats.prefix(), name, *parts))


def level_regions(level):
    """The regions an Areas level shades: covered counties, ZIP areas, 2020 tracts."""
    queryset = Region.objects.counties() if level == Region.Type.COUNTY else Region.objects.filter(type=level)
    return queryset.filter(boundary__isnull=False).current_vintage()


def containing_region(level, point_field='point'):
    """
    The Region of `level` whose boundary contains a point field on the outer
    query (`intersects`, so a point exactly on a shared border still lands
    somewhere, and `[:1]` so it lands in only one). Shared by facility and
    dairy region indexes.
    """
    return (
        level_regions(level).filter(boundary__geometry__intersects=OuterRef(point_field))
        .order_by('pk').values('pk')[:1]
    )


def region_index(level):
    """
    {facility pk: region pk} for one level. Counties by Facility.county;
    otherwise the region the facility's point falls in. Facilities without a
    point are only in counties.
    """
    def compute():
        if level == Region.Type.COUNTY:
            return dict(Facility.objects.exclude(county=None).values_list('pk', 'county_id'))
        containing = containing_region(level)
        rows = Facility.objects.exclude(point=None).annotate(region_pk=Subquery(containing)).values_list('pk', 'region_pk')
        return {facility: region for facility, region in rows if region is not None}
    return cache.get_or_set(_key('region-index', level), compute, stats.CACHE_TIMEOUT)


def region_sq_miles(level):
    """{region pk: square miles}, from the full boundary in California Albers."""
    def compute():
        rows = (
            level_regions(level)
            .annotate(area=AreaOf(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS)))
            .values_list('pk', 'area')
        )
        return {pk: area.sq_m / SQ_METERS_PER_SQ_MILE for pk, area in rows if area}
    return cache.get_or_set(_key('region-sq-miles', level), compute, stats.CACHE_TIMEOUT)


def _per(total, divisor, scale=1):
    return total / divisor * scale if total is not None and divisor else None


def _area_sums(scope, level, sector, index):
    """{region pk: summed value} over every facility in `scope` that falls in `level`, through stats.values()."""
    sums, counts = {}, {}
    for facility_id, value in stats.values(scope, sector=sector):
        region = index.get(facility_id)
        if region is None:
            continue
        counts[region] = counts.get(region, 0) + 1
        sums[region] = sums.get(region, 0.0) + float(value or 0)
    return counts, sums


def area_values(scope, level, sector=None, compare=None):
    """
    What the Areas view shades: per region with facilities in `scope`, its
    count, total and the two rates. `compare` (a loaded year, not
    `scope.year`) adds the same total and rates for that year under a
    `_prev` suffix, for every region already in the result -- both years
    travel together so the map's Compare toggle needs no refetch. A region
    with nothing in `scope` doesn't appear even if `compare`'s year had
    facilities there: the view is always framed on the current year's map,
    so a region whose only facilities closed before it isn't shown. The
    `_prev` fields are left out (null) when the compared year's total is
    below stats.SMALL_BASELINE_FLOOR for the unit -- too small a baseline
    for a percent change to mean anything. For a weighted measure (`unit ==
    'share'`) the two rates are meaningless (a share isn't a quantity a
    square mile or a resident count can divide), so they're always None.
    """
    def compute():
        index = region_index(level)
        counts, sums = _area_sums(scope, level, sector, index)
        compare_sums = {}
        if compare:
            _, compare_sums = _area_sums(replace(scope, year=compare), level, sector, index)
        miles = region_sq_miles(level)
        is_share = scope.pollutant.unit == 'share'
        regions = Region.objects.filter(pk__in=counts).values_list('pk', 'sqid', 'metadata')
        result = []
        for pk, sqid, metadata in regions:
            total = scope.pollutant.display(sums[pk])
            row = {
                'id': sqid,
                'facilities': counts[pk],
                'total': total,
                'per_sq_mi': None if is_share else _per(total, miles.get(pk)),
                'per_1k_residents': None if is_share else _per(total, (metadata or {}).get('population'), 1000),
            }
            if compare:
                prev_total = scope.pollutant.display(compare_sums[pk]) if pk in compare_sums else None
                if prev_total is not None and not stats.comparable_baseline(prev_total, scope.pollutant.unit):
                    prev_total = None
                row.update({
                    'total_prev': prev_total,
                    'per_sq_mi_prev': None if is_share else _per(prev_total, miles.get(pk)),
                    'per_1k_residents_prev': None if is_share else _per(prev_total, (metadata or {}).get('population'), 1000),
                })
            result.append(row)
        result.sort(key=lambda area: area['id'])
        rows = stats.records(scope)
        if sector:
            rows = rows.filter(facility__sector=sector)
        without_point = 0 if level == Region.Type.COUNTY else rows.filter(facility__point=None).count()
        return {
            'level': level, 'unit': scope.pollutant.unit, 'facilities_without_point': without_point,
            'compare': compare or None, 'areas': result,
        }
    return cache.get_or_set(scope.key('areas', level, sector or '', compare or ''), compute, stats.CACHE_TIMEOUT)


# What the facility list's region filter searches: the community layers
# (cities, urban areas and CDPs, each as-is) and ZIP codes.
FILTER_REGION_TYPES = {
    **Region.COMMUNITY_LABELS,
    Region.Type.AB617_COMMUNITY: 'AB 617 community',
    Region.Type.ZIPCODE: 'ZIP',
}


@dataclass(frozen=True)
class RegionArea:
    """A Scope narrowed to one region (a region page)."""
    region: Region

    @property
    def key(self):
        return f'region-{self.region.pk}'

    def q(self):
        region = self.region
        if region.type == Region.Type.COUNTY:
            return Q(facility__county=region)
        if region.type in LEVELS:
            ids = [facility for facility, pk in region_index(region.type).items() if pk == region.pk]
            return Q(facility_id__in=ids)
        return Q(facility__point__intersects=region.boundary.geometry)

    def dairy_q(self):
        """
        The same area as a Q on DairyHerd: counties by the dairy's county, ZIP
        areas and tracts by its point, CITY and CDP by its point OR its mailing
        city (Dairy.address['city']) resolving to the region (cities.resolve(),
        aliases included), and every other type, urban areas too, by point alone.
        """
        from camp.apps.emissions import dairies  # dairies imports this module

        region = self.region
        if region.type == Region.Type.COUNTY:
            return Q(dairy__county=region)
        if region.type in LEVELS:
            ids = [dairy for dairy, pk in dairies.region_index(region.type).items() if pk == region.pk]
            return Q(dairy_id__in=ids)
        point_q = Q(dairy__point__intersects=region.boundary.geometry)
        if region.type in cities.TYPES:
            for name in cities.mailing_names(region, cities.regions_by_name()):
                point_q |= Q(dairy__address__city__iexact=name)
        return point_q

    @property
    def sq_miles(self):
        if self.region.type in LEVELS:
            return region_sq_miles(self.region.type).get(self.region.pk)
        geometry = self.region.boundary.geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
        return geometry.area / SQ_METERS_PER_SQ_MILE

    @property
    def population(self):
        return (self.region.metadata or {}).get('population')


@dataclass(frozen=True)
class ValleyArea:
    """Every covered county at once: the top-level Oil & gas tab, which runs the area tab's wells helpers on the whole Valley."""

    @property
    def key(self):
        return 'valley'


@dataclass(frozen=True)
class RadiusArea:
    """A Scope narrowed to a circle around a point (near-me)."""
    lat: float
    lng: float
    radius: int

    @property
    def key(self):
        return f'near-{self.lat:.4f}-{self.lng:.4f}-{self.radius}'

    @property
    def point(self):
        return Point(self.lng, self.lat, srid=EPSG_LATLON)

    @property
    def geometry(self):
        """The circle as a polygon in WGS84, buffered in California Albers so a mile is a mile (for CES tract membership)."""
        albers = self.point.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
        return albers.buffer(self.radius * METERS_PER_MILE).transform(EPSG_LATLON, clone=True)

    def _within(self, field):
        # A bounding-box prefilter first, so the index does the work and the
        # exact distance runs on a handful of rows.
        dlat = self.radius / MILES_PER_DEGREE
        dlng = self.radius / (MILES_PER_DEGREE * max(math.cos(math.radians(self.lat)), 0.01))
        box = Polygon.from_bbox((self.lng - dlng, self.lat - dlat, self.lng + dlng, self.lat + dlat))
        box.srid = EPSG_LATLON
        return Q(**{f'{field}__bboverlaps': box, f'{field}__distance_lte': (self.point, D(mi=self.radius))})

    def q(self):
        return self._within('facility__point')

    def dairy_q(self):
        return self._within('dairy__point')

    @property
    def sq_miles(self):
        return math.pi * self.radius ** 2

    @property
    def population(self):
        return None


def facility_areas(facility):
    """The regions a facility counts in: its county, then the ZIP area and tract its point is in."""
    pks = [facility.county_id] if facility.county_id else []
    for level in (Region.Type.ZIPCODE, Region.Type.TRACT):
        pk = region_index(level).get(facility.pk)
        if pk:
            pks.append(pk)
    regions = Region.objects.in_bulk(pks)
    return [regions[pk] for pk in pks if pk in regions]


def facility_ab617_region(facility):
    """
    The AB 617 community whose boundary contains the facility's point, or
    None (no point, or the point falls outside every community). Point-in-
    boundary, like every other non-county area -- a facility isn't indexed
    by AB 617 community in region_index() since there are only a handful of
    communities and this is only ever called once, on a facility's own page.
    """
    if facility.point is None:
        return None
    return (
        Region.objects.filter(type=Region.Type.AB617_COMMUNITY, boundary__isnull=False)
        .filter(boundary__geometry__intersects=facility.point)
        .select_related('boundary').first()
    )


# An area page's maps can reach past its boundary: exactly the area, or 1,
# 3 or 5 miles beyond it (?buffer=). A region's widened shape is the shared
# regions.shapes.region_shape (pesticides' region maps use it too); a
# near-me circle is widened here, the same way.
BUFFERS = shapes.BUFFERS
buffer_param = shapes.buffer_param


def map_shape(area, buffer=0):
    """
    An area's shape for its maps (EPSG:4326): a region's boundary or a radius's
    circle, widened by `buffer` miles in California Albers (so a mile is a
    mile). A circle's widened shape is cached a day here; a region's, by
    regions.shapes.
    """
    if isinstance(area, RegionArea):
        return shapes.region_shape(area.region, buffer)
    if not buffer:
        return area.geometry

    def compute():
        shape = area.geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
        shape = shape.buffer(buffer * METERS_PER_MILE).simplify(shapes.BUFFER_SIMPLIFY, preserve_topology=True)
        shape.transform(EPSG_LATLON)
        return shape.hexewkb.decode() if isinstance(shape.hexewkb, bytes) else shape.hexewkb

    return GEOSGeometry(cache.get_or_set(_key('map-shape', area.key, buffer), compute, stats.CACHE_TIMEOUT))
