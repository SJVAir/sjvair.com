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

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup
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
    """Entity/county/month filters shared by both endpoints. Returns (rows, error)."""
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
    return rows, None


def parse_year(params):
    return stats.resolve_year(params.get('year'))


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


def county_name_for(section_pks, year):
    """{mtrs_id: county_name} built once from the rollup, not spatially."""
    return {
        row['mtrs']: row['county__name']
        for row in (
            PesticideUseRollup.objects
            .filter(mtrs__in=section_pks, year=year)
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
        if params.get('bbox'):
            try:
                west, south, east, north = (float(v) for v in params['bbox'].split(','))
            except ValueError:
                return None, 'bbox must be west,south,east,north'
            if not (west < east and south < north):
                return None, 'bbox must be west,south,east,north'
            return sections.filter(boundary__geometry__bboverlaps=Polygon.from_bbox((west, south, east, north))), None
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
        year = parse_year(params)

        rows = PesticideUseRollup.objects.filter(year=year, mtrs__in=section_pks)
        rows, error = apply_filters(rows, params)
        if error:
            return bad_request(error)
        totals = {r['mtrs']: r for r in rows.values('mtrs').annotate(**TOTALS)}
        counties = county_name_for(section_pks, year)

        section_qs = Region.objects.filter(pk__in=section_pks).select_related('boundary').order_by('external_id')
        features = []
        for section in section_qs:
            t = totals.get(section.pk, ZERO)
            features.append({
                'type': 'Feature',
                'id': section.sqid,
                'geometry': json.loads(section.boundary.geometry.geojson),
                'properties': {
                    'id': section.sqid,
                    'mtrs': section.external_id,
                    'county': counties.get(section.pk),
                    'lbs_chemical': t['lbs_chemical'] or 0,
                    'lbs_product': t['lbs_product'] or 0,
                    'acres_treated': t['acres_treated'] or 0,
                    'applications': t['applications'] or 0,
                },
            })
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'year': year, 'features': features}


class SectionList(CachedEndpointMixin, SectionListBase):
    """
    MTRS sections with pesticide-use totals, as GeoJSON.

    Give either `bbox=west,south,east,north` or `lat`, `lng`, `radius` (miles: 1, 3, or 5).
    Filters: `year` (default latest), `month`, `chemical` (chem code), `product`
    (prodno), `commodity` (site code), `county` (slug).
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
        year = parse_year(request.GET)
        rows = PesticideUseRollup.objects.filter(mtrs=section)
        years = list(rows.values('year').annotate(**TOTALS).order_by('-year'))
        months = stats.by_month(rows, year) if year else []
        county = rows.values_list('county__name', flat=True).order_by('county__name').first()

        def top(field, lbs_field='lbs_chemical', limit=5):
            related = stats.top_related(rows, year, field, lbs_field=lbs_field, limit=limit) if year else []
            return [{'id': r.obj.sqid, 'name': r.obj.name, 'lbs': r.lbs} for r in related]

        return {
            'id': section.sqid,
            'mtrs': section.external_id,
            'county': county,
            'year': year,
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
    """One MTRS section: geometry, totals by year and by month, and top chemicals, products, and commodities for `year` (default latest)."""
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
            try:
                west, south, east, north = (float(v) for v in params['bbox'].split(','))
            except ValueError:
                return bad_request('bbox must be west,south,east,north')
            if not (west < east and south < north):
                return bad_request('bbox must be west,south,east,north')
            notices = notices.filter(point__bboverlaps=Polygon.from_bbox((west, south, east, north)))
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
                'products': [{'id': p.sqid, 'name': p.name} for p in n.products.all()],
                'chemicals': [{'id': c.sqid, 'name': c.name, 'is_of_concern': c.is_of_concern} for c in n.chemicals.all()],
            },
        } for n in notices]
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'as_of': timezone.now().isoformat(), 'features': features}


class ActiveNoticeList(CachedEndpointMixin, ActiveNoticeListBase):
    """Active SprayDays notices of intent (scheduled from four days ago onward) as GeoJSON points. Optional `bbox=west,south,east,north`, `chemical` (chem code), `product` (prodno), `county` (slug). A request matching more than 2000 notices returns 400; narrow it with a bbox or a filter."""
    cache_timeout = NOTICE_CACHE_TTL
