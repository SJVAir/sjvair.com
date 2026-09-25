"""
Section-level (MTRS, one square mile) pesticide use for the explorer maps.
Totals come from PesticideUseRollup; geometry from the MTRS Region boundaries.
"""
import json
import math

from datetime import timedelta

from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from resticus import generics, http

from camp.apps.pesticides import maps, stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup
from camp.apps.pesticides.townships import round_coords, township_geometries
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin

MAX_SECTIONS = 2500
MAX_NOTICES = 2000
NOTICE_CACHE_TTL = 300
TOTALS = {
    'lbs_chemical': Sum('lbs_chemical'),
    'lbs_product': Sum('lbs_product'),
    'acres_treated': Sum('acres_treated'),
    'applications': Sum('applications'),
}
ZERO = {'lbs_chemical': 0, 'lbs_product': 0, 'acres_treated': 0, 'applications': 0}


def allowed_radii():
    """
    The one list of allowed radii, `places.RADIUS_CHOICES`. Imported lazily:
    `places` imports this module for `radius_bbox`, so a module-level import
    here would be circular.
    """
    from camp.apps.pesticides.places import RADIUS_CHOICES
    return RADIUS_CHOICES


def bad_request(message):
    # Returned through CachedEndpointMixin, which caches it for the same bad
    # querystring; harmless, since the same params always produce the same error.
    return http.Http400({'error': message})


def apply_filters(rows, params):
    """Entity/county/month/concern filters shared by both endpoints. Returns (rows, error)."""
    if params.get('month'):
        try:
            month = int(params['month'])
        except ValueError:
            return rows, 'month must be 1-12'
        if not 1 <= month <= 12:
            return rows, 'month must be 1-12'
        rows = rows.filter(month=month)
    cast_lookups = {
        'chemical': ('chemical__chem_code', int),
        'product': ('product__prodno', int),
    }
    for param, (lookup, cast) in cast_lookups.items():
        value = params.get(param)
        if value:
            try:
                rows = rows.filter(**{lookup: cast(value)})
            except ValueError:
                return rows, f'{param} is invalid'
    direct_lookups = {
        'commodity': 'commodity__site_code',
        'county': 'county__slug',
    }
    for param, lookup in direct_lookups.items():
        value = params.get(param)
        if value:
            rows = rows.filter(**{lookup: value})
    narrow = stats.resolve_narrow(params)
    if narrow:
        rows = stats.narrow_rows(rows, narrow)
    return rows, None


def parse_year(params):
    """`(year, all_years)`: a concrete year, or every loaded year for `year=all`."""
    return stats.resolve_year_param(params.get('year'))


def parse_compare(params, year, all_years):
    """
    `(compare, error)` for `?compare=`: the year to return alongside the scope
    year, or None when there is nothing to compare against. A value that names
    no loaded year is an error rather than a silent single-year response --
    the map would otherwise draw a sequential view while its legend said
    "change". The scope year itself, and any value under `year=all`, are
    simply no comparison.
    """
    requested = params.get('compare')
    if not requested:
        return None, None
    compare = stats.resolve_compare_param(requested, year, all_years)
    if compare is None:
        if all_years or str(requested).strip() == str(year):
            return None, None
        return None, 'compare must be a loaded year'
    return compare, None


def totals_properties(totals, previous=None):
    """
    The four per-feature totals, plus the compared year's under a `_prev`
    suffix when there is one. Both years travel rather than a delta: the
    popup shows both numbers anyway, so sending them costs four floats and
    buys metric switching with no refetch.
    """
    properties = {key: (totals[key] or 0) for key in TOTALS}
    if previous is not None:
        properties.update({f'{key}_prev': (previous[key] or 0) for key in TOTALS})
    return properties


def year_value(year, all_years):
    """The `year` a response echoes back: the year, or "all"."""
    return stats.ALL_YEARS if all_years else year


def parse_bbox(value):
    """((west, south, east, north), None) or (None, error). NaN fails the ordering check."""
    try:
        west, south, east, north = (float(v) for v in value.split(','))
    except ValueError:
        return None, 'bbox must be west,south,east,north'
    if not (west < east and south < north):
        return None, 'bbox must be west,south,east,north'
    return (west, south, east, north), None


def bbox_overlaps(a, b):
    """Do two (west, south, east, north) boxes overlap? Edge contact counts."""
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def radius_bbox(lat, lng, miles):
    """
    Degree bbox that contains a circle of `miles` around (lat, lng), slightly
    generous. Used as an index-friendly prefilter for the radius query --
    `boundary__geometry__distance_lte` alone forces a full scan of
    regions_boundary because the planner can't use the geometry GiST index
    on a raw distance filter. Bounding-box overlap can, so we apply it first
    and keep the exact distance check as the real filter.
    """
    lat_deg = miles / 69.0
    lng_deg = miles / (69.0 * max(math.cos(math.radians(lat)), 0.01))
    return Polygon.from_bbox((lng - lng_deg, lat - lat_deg, lng + lng_deg, lat + lat_deg))


def county_boundary(slug):
    """The county's boundary geometry (WGS84) for `slug`, or None when there's no such county or it has no boundary."""
    county = Region.objects.filter(type=Region.Type.COUNTY, slug=slug, boundary__isnull=False).select_related('boundary').first()
    if county is None:
        return None
    geometry = county.boundary.geometry
    if geometry.srid and geometry.srid != 4326:
        geometry = geometry.transform(4326, clone=True)
    return geometry


def county_name_for(section_pks, year, all_years=False):
    """{mtrs_id: county_name} built once from the rollup, not spatially."""
    rows = PesticideUseRollup.objects.filter(mtrs__in=section_pks)
    return {
        row['mtrs']: row['county__name']
        for row in (
            stats.in_year(rows, year, all_years)
            .values('mtrs', 'county__name')
            .order_by('mtrs', 'county__name')
            .distinct()
        )
    }


class SectionListBase(generics.Endpoint):
    # Business logic lives here, separate from SectionList below, so that
    # CachedEndpointMixin.get() -- not this class's get() -- is the method
    # the URLconf actually dispatches to. A `get()` defined directly on
    # SectionList would shadow the mixin's caching wrapper entirely: Python
    # resolves methods defined directly on a class before anything in its
    # MRO, regardless of base-class order.
    def get_sections(self, params):
        sections = Region.objects.filter(type=Region.Type.MTRS, boundary__isnull=False).select_related('boundary')
        # A county filter narrows the geometry as well as the numbers, so the
        # map shows that county alone. Sections straddling the line stay (a
        # use record is filed under one county; the shading is that county's).
        if params.get('county'):
            boundary = county_boundary(params['county'])
            if boundary is not None:
                sections = sections.filter(boundary__geometry__intersects=boundary)
        if params.get('bbox'):
            bbox, error = parse_bbox(params['bbox'])
            if error:
                return None, error
            return sections.filter(boundary__geometry__bboverlaps=Polygon.from_bbox(bbox)), None
        if params.get('lat') and params.get('lng'):
            try:
                lat, lng = float(params['lat']), float(params['lng'])
                radius = int(params.get('radius', 1))
            except ValueError:
                return None, 'lat, lng, and radius must be numbers'
            if not (math.isfinite(lat) and math.isfinite(lng)):
                return None, 'lat and lng must be numbers'
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return None, 'lat must be -90..90 and lng -180..180'
            radii = allowed_radii()
            if radius not in radii:
                return None, f'radius must be one of {", ".join(str(r) for r in radii)}'
            point = Point(lng, lat, srid=4326)
            return sections.filter(
                boundary__geometry__bboverlaps=radius_bbox(lat, lng, radius),
                boundary__geometry__distance_lte=(point, D(mi=radius)),
            ), None
        return None, 'give bbox=west,south,east,north or lat, lng, and radius'

    def get(self, request):
        params = request.GET
        sections, error = self.get_sections(params)
        if error:
            return bad_request(error)
        # Evaluate the spatial query exactly once: .count() on a queryset and
        # then iterating it again would run the same (expensive) spatial
        # lookup twice.
        section_pks = list(sections.values_list('pk', flat=True))
        if len(section_pks) > MAX_SECTIONS:
            too_large = 'bbox too large; zoom in' if params.get('bbox') else 'radius too large'
            return bad_request(too_large)
        year, all_years = parse_year(params)

        compare, error = parse_compare(params, year, all_years)
        if error:
            return bad_request(error)

        in_bbox = PesticideUseRollup.objects.filter(mtrs__in=section_pks)
        rows = stats.in_year(in_bbox, year, all_years)
        rows, error = apply_filters(rows, params)
        if error:
            return bad_request(error)
        totals = {r['mtrs']: r for r in rows.values('mtrs').annotate(**TOTALS)}
        previous = {}
        if compare:
            # The same filters over the compared year, so the change is the
            # one the reader's filters describe and not the section's total.
            compare_rows, _ = apply_filters(stats.in_year(in_bbox, compare), params)
            previous = {r['mtrs']: r for r in compare_rows.values('mtrs').annotate(**TOTALS)}
        counties = county_name_for(section_pks, year, all_years)

        section_qs = Region.objects.filter(pk__in=section_pks).select_related('boundary').order_by('external_id')
        features = []
        for section in section_qs:
            t = totals.get(section.pk, ZERO)
            features.append({
                'type': 'Feature',
                'id': section.sqid,
                'geometry': round_coords(json.loads(section.boundary.geometry.geojson)),
                'properties': {
                    'id': section.sqid,
                    'mtrs': section.external_id,
                    'county': counties.get(section.pk),
                    **totals_properties(t, previous.get(section.pk, ZERO) if compare else None),
                },
            })
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'year': year_value(year, all_years), 'features': features}


class SectionList(CachedEndpointMixin, SectionListBase):
    """
    MTRS sections with pesticide-use totals, as GeoJSON.

    Give either `bbox=west,south,east,north` or `lat`, `lng`, `radius` (miles: 1, 3, or 5).
    Filters: `year` (default latest), `month`, `chemical` (chem code), `product`
    (prodno), `commodity` (site code), `county` (slug), and `concern=1` to
    count only the chemicals of concern (Prop 65, CARB TAC, IARC 1/2A/2B).
    """
    cache_timeout = 60 * 60


class SectionDetailBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on SectionDetail below
    # is the one actually dispatched to.
    def get(self, request, section_id):
        section = get_object_or_404(
            Region.objects.filter(type=Region.Type.MTRS).select_related('boundary'), sqid=section_id,
        )
        year, all_years = parse_year(request.GET)
        rows = PesticideUseRollup.objects.filter(mtrs=section)
        narrow = stats.resolve_narrow(request.GET)
        if narrow:
            rows = stats.narrow_rows(rows, narrow)
        years = list(rows.values('year').annotate(**TOTALS).order_by('-year'))
        months = stats.by_month(rows, year, all_years=all_years) if (year or all_years) else []
        county = rows.values_list('county__name', flat=True).order_by('county__name').first()

        def top(field, lbs_field='lbs_chemical', limit=5):
            if not (year or all_years):
                return []
            related = stats.top_related(rows, year, field, lbs_field=lbs_field, limit=limit, all_years=all_years)
            entries = []
            for r in related:
                entry = {'id': r.obj.sqid, 'name': r.obj.name, 'display_name': r.obj.display_name, 'lbs': r.lbs}
                # The map's section popup marks the chemicals of concern.
                if field == 'chemical':
                    entry['is_of_concern'] = r.obj.is_of_concern
                entries.append(entry)
            return entries

        return {
            'id': section.sqid,
            'mtrs': section.external_id,
            'county': county,
            'year': year_value(year, all_years),
            'geometry': json.loads(section.boundary.geometry.geojson) if section.boundary else None,
            'years': years,
            'months': [
                {'month': m['month'], 'lbs_chemical': m['lbs'], 'acres_treated': m['acres'], 'applications': m['applications']}
                for m in months
            ],
            'top_chemicals': top('chemical'),
            'top_products': top('product', lbs_field='lbs_product'),
            'top_commodities': top('commodity'),
        }


class SectionDetail(CachedEndpointMixin, SectionDetailBase):
    """One MTRS section: geometry, totals by year and by month, and top chemicals, products, and commodities for `year` (default latest). `concern=1` counts only the chemicals of concern."""
    cache_timeout = 60 * 60


class ActiveNoticeListBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on ActiveNoticeList
    # below is the one actually dispatched to.
    def get(self, request):
        params = request.GET
        notices = stats._upcoming(PesticideNotice.objects.all()).select_related(
            'county', 'mtrs',
        ).prefetch_related('chemicals', 'products').order_by('scheduled_application', 'pk')
        if params.get('bbox'):
            bbox, error = parse_bbox(params['bbox'])
            if error:
                return bad_request(error)
            notices = notices.filter(point__bboverlaps=Polygon.from_bbox(bbox))
        for param, lookup, cast in (
            ('chemical', 'chemicals__chem_code', int),
            ('product', 'products__prodno', int),
            ('county', 'county__slug', str),
        ):
            value = params.get(param)
            if value:
                try:
                    notices = notices.filter(**{lookup: cast(value)})
                except ValueError:
                    return bad_request(f'{param} is invalid')
        # Same shape of cap as SectionList's MAX_SECTIONS: an unbounded
        # response (no bbox, or one covering the whole valley) would serialize
        # every active notice in the state. Counting first keeps that off the
        # serialization path entirely.
        notices = notices.distinct()
        if notices.count() > MAX_NOTICES:
            return bad_request('bbox too large; zoom in')

        grace = timedelta(days=stats.NOTICE_GRACE_DAYS)
        features = [{
            'type': 'Feature',
            'id': n.sqid,
            'geometry': json.loads(n.point.geojson) if n.point else None,
            'properties': {
                'id': n.sqid,
                'scheduled_application': n.scheduled_application.isoformat(),
                'scheduled_end': (n.scheduled_application + grace).isoformat(),
                'county': n.county.name if n.county else None,
                'application_method': n.application_method,
                'treated_amount': n.treated_amount,
                'treated_units': n.treated_units,
                'section': n.mtrs.external_id if n.mtrs else None,
                'section_id': n.mtrs.sqid if n.mtrs else None,
                'products': [{'id': p.sqid, 'name': p.name} for p in n.products.all()],
                'chemicals': [{'id': c.sqid, 'name': c.name, 'display_name': c.display_name, 'is_of_concern': c.is_of_concern} for c in n.chemicals.all()],
            },
        } for n in notices]
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'as_of': timezone.now().isoformat(), 'features': features}


class CountyListBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on CountyList below is
    # the one actually dispatched to.
    def get(self, request):
        # Already cached by maps.county_geometries(); one
        # in_bulk() for the names, which aren't part of the geometry cache.
        geometries = maps.county_geometries()
        regions = Region.objects.in_bulk(list(geometries))
        features = [{
            'type': 'Feature',
            'id': regions[pk].sqid,
            'geometry': round_coords(json.loads(geojson)),
            'properties': {
                'id': regions[pk].sqid,
                'name': regions[pk].name,
                'slug': regions[pk].slug,
            },
        } for pk, geojson in geometries.items() if pk in regions]
        features.sort(key=lambda feature: feature['properties']['name'])
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'features': features}


class CountyList(CachedEndpointMixin, CountyListBase):
    """The eight San Joaquin Valley county outlines as GeoJSON. No parameters."""
    cache_timeout = 60 * 60 * 24
    # The outlines are full precision as of v2; a cached v1 response is the
    # simplified set, whose shared borders doubled up when drawn.
    cache_key_version = 2


class TownshipListBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on TownshipList below
    # is the one actually dispatched to.
    def get(self, request):
        params = request.GET
        bbox = None
        if params.get('bbox'):
            bbox, error = parse_bbox(params['bbox'])
            if error:
                return bad_request(error)
        year, all_years = parse_year(params)

        compare, error = parse_compare(params, year, all_years)
        if error:
            return bad_request(error)

        rows = stats.in_year(PesticideUseRollup.objects.all(), year, all_years)
        rows, error = apply_filters(rows, params)
        if error:
            return bad_request(error)
        totals = stats.by_township(rows, year, all_years)
        previous = {}
        if compare:
            compare_rows, _ = apply_filters(
                stats.in_year(PesticideUseRollup.objects.all(), compare), params)
            previous = stats.by_township(compare_rows, compare)

        # The map keeps township outlines from its first load and asks for
        # `geometry=0` after that (a year or filter change only moves the
        # numbers), so those responses are a few KB instead of a few hundred.
        with_geometry = params.get('geometry') != '0'

        # A county filter narrows the geometry as well as the numbers: keep
        # the townships whose centre is in the county, plus any with use
        # filed under it (a border township whose records say this county).
        boundary = county_boundary(params['county']) if params.get('county') else None

        # No cap: there are only a few hundred townships in the valley, so
        # the whole grid is a small response even unfiltered.
        features = []
        for township, geometry in sorted(township_geometries().items()):
            if bbox and not bbox_overlaps(bbox, geometry['bbox']):
                continue
            t = totals.get(township, ZERO)
            if boundary is not None and not t['applications']:
                west, south, east, north = geometry['bbox']
                if not boundary.contains(Point((west + east) / 2, (south + north) / 2, srid=4326)):
                    continue
            features.append({
                'type': 'Feature',
                'id': township,
                'geometry': geometry['geometry'] if with_geometry else None,
                'properties': {
                    'id': township,
                    'name': township,
                    'sections': geometry['sections'],
                    **totals_properties(t, previous.get(township, ZERO) if compare else None),
                },
            })
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'year': year_value(year, all_years), 'features': features}


class TownshipList(CachedEndpointMixin, TownshipListBase):
    """
    PLSS townships (6x6 blocks of MTRS sections) with pesticide-use totals, as GeoJSON.

    Each township is the union of its sections. Optional
    `bbox=west,south,east,north` limits the grid to what's on screen, and
    `geometry=0` returns the features with `null` geometry (values only) for
    a client that already holds the outlines.
    Filters: `year` (default latest), `month`, `chemical` (chem code),
    `product` (prodno), `commodity` (site code), `county` (slug), and
    `concern=1` to count only the chemicals of concern.
    """
    cache_timeout = 60 * 60


class ActiveNoticeList(CachedEndpointMixin, ActiveNoticeListBase):
    """Active SprayDays notices of intent (scheduled from four days ago onward) as GeoJSON points. Optional `bbox=west,south,east,north`, `chemical` (chem code), `product` (prodno), `county` (slug). A request matching more than 2000 notices returns 400; narrow it with a bbox or a filter."""
    cache_timeout = NOTICE_CACHE_TTL
