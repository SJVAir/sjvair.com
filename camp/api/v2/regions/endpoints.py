import json

from django import forms
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import connection
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from resticus import generics, http

from camp.apps.regions import shapes
from django.db.models import Q

from camp.apps.regions.locations import SOURCES
from camp.apps.regions.models import Boundary, Location, Region
from camp.apps.regions.resolve import (
    PlaceError, PlaceNotFound, monitor_lookup_key, parse_lookup_types, point_lookup_key,
    regions_containing, resolve_place, round_point)
from camp.utils.views import CachedEndpointMixin

from .filters import LOOKUP_MAX_CODES, RegionFilter, parse_codes
from .serializers import LocationSerializer, RegionListSerializer, RegionSerializer


WITHIN_MODES = ('contained', 'overlaps')
# The share of a region's own area that must fall inside another for the two
# to count as overlapping (the same floor Region.objects.overlapping uses).
ALSO_IN_MIN_FRACTION = 0.01
META_COUNT_CACHE_KEY = 'regions:meta:counts'
META_COUNT_CACHE_TIMEOUT = 60 * 60


class PlaceQueryForm(forms.Form):
    q = forms.CharField(required=False, strip=True)
    type = forms.CharField(required=False, strip=True)


class RegionMixin:
    model = Region
    serializer_class = RegionSerializer

    def get_queryset(self):
        return super().get_queryset().select_related('boundary', 'replaced_by')


class RegionList(RegionMixin, generics.ListEndpoint):
    # A listing: current regions only. (The model's default manager,
    # all_objects, would include retired ones.)
    queryset = Region.objects.all()
    filter_class = RegionFilter
    paginate = False
    serializer_class = RegionListSerializer

    def lookup_error(self):
        """The 400 for a malformed ?external_id= lookup or ?within_mode=, or None."""
        if self.request.GET.get('within_mode', 'contained') not in WITHIN_MODES:
            return http.Http400({'error': 'within_mode must be contained or overlaps.'})
        if 'external_id' not in self.request.GET:
            return None
        region_type = self.request.GET.get('type', '').strip()
        if not region_type:
            return http.Http400({'error': 'The type parameter is required with external_id.'})
        if region_type == Region.Type.LAND_USE:
            return http.Http400({'error': "Land-use regions can't be looked up by code yet."})
        if len(parse_codes(self.request.GET['external_id'])) > LOOKUP_MAX_CODES:
            return http.Http400({'error': f'At most {LOOKUP_MAX_CODES} codes can be looked up at once.'})
        return None

    def get(self, request, *args, **kwargs):
        return self.lookup_error() or super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        if 'external_id' in self.request.GET:
            # A lookup by code: retired regions are answered too (flagged),
            # since a stored code must keep resolving. Unknown codes just
            # don't appear.
            codes = parse_codes(self.request.GET['external_id'])
            qs = Region.all_objects.select_related('boundary', 'replaced_by').filter(external_id__in=codes)
        within_ids = [value for value in self.request.GET.getlist('within') if value.strip()]
        if within_ids:
            # Parents are named by id, so a retired one still narrows.
            geometry = Region.all_objects.filter(sqid__in=within_ids).combined_geometry()
            if geometry is None or geometry.empty:
                # `within` was asked for but nothing resolved (unknown ids, or
                # parents with no boundary): nothing can be inside it. Falling
                # back to the unnarrowed list here would silently hand back
                # every region in the database.
                return qs.none()
            if self.overlaps_mode():
                qs = qs.overlapping(geometry)
            else:
                qs = qs.contained_within(geometry)
        return qs

    def overlaps_mode(self):
        return (
            self.request.GET.get('within_mode') == 'overlaps'
            and any(value.strip() for value in self.request.GET.getlist('within'))
        )

    def also_in_map(self, regions):
        """
        {region pk: [{type, external_id, name}]} for the listed regions: the
        other current regions of the requested parents' type that each
        overlaps by at least ALSO_IN_MIN_FRACTION of its own area. One query
        pairs every result with its candidates in the database, so the query
        count doesn't grow with the number of results and no geometry is
        loaded into Python.

        Both sides are narrowed first in MATERIALIZED CTEs: joined straight to
        the boundary table, the planner pairs each result with every boundary
        its bbox touches (MTRS sections, tracts, old vintages: ~300 apiece)
        and runs ST_Intersection on each before the few candidates filter
        them out, which took ~4 s for Fresno County's ZIPs (now ~50 ms).
        """
        within_ids = [value for value in self.request.GET.getlist('within') if value.strip()]
        result_ids = [r.pk for r in regions if r.boundary_id]
        if not within_ids or not result_ids:
            return {}
        parents = Region.all_objects.filter(sqid__in=within_ids)
        candidates = (
            Region.objects.filter(type__in=parents.values('type'))
            .exclude(pk__in=parents.values('pk'))
            .current_vintage().values('pk')
        )
        candidate_sql, candidate_params = candidates.query.sql_with_params()
        region_table = connection.ops.quote_name(Region._meta.db_table)
        boundary_table = connection.ops.quote_name(Boundary._meta.db_table)
        sql = f"""
            WITH candidates AS MATERIALIZED (
                SELECT c.id, c.type, c.external_id, c.name, cb.geometry
                FROM {region_table} c
                JOIN {boundary_table} cb ON cb.id = c.boundary_id
                WHERE c.id IN ({candidate_sql})
            ), results AS MATERIALIZED (
                SELECT r.id, rb.geometry, ST_Area(rb.geometry) AS area
                FROM {region_table} r
                JOIN {boundary_table} rb ON rb.id = r.boundary_id
                WHERE r.id = ANY(%s)
            )
            SELECT r.id, c.type, c.external_id, c.name
            FROM results r
            JOIN candidates c ON ST_Intersects(c.geometry, r.geometry)
            WHERE r.area > 0
              AND ST_Area(ST_Intersection(r.geometry, c.geometry)) >= %s * r.area
            ORDER BY c.name, c.id
        """
        result = {}
        with connection.cursor() as cursor:
            cursor.execute(sql, [*candidate_params, result_ids, ALSO_IN_MIN_FRACTION])
            for pk, region_type, external_id, name in cursor.fetchall():
                result.setdefault(pk, []).append(
                    {'type': region_type, 'external_id': external_id, 'name': name})
        return result

    def serialize(self, source, *args, **kwargs):
        if not self.overlaps_mode() or isinstance(source, Region):
            return super().serialize(source, *args, **kwargs)
        regions = list(source)
        also_in = self.also_in_map(regions)

        def fixup(region, data):
            data['also_in'] = also_in.get(region.pk, [])
            return data

        return super().serialize(regions, *args, fixup=fixup, **kwargs)


class RegionGeoJSONBase(RegionList):
    """
    The region list's filters, answered as a GeoJSON FeatureCollection for a
    map to draw: one MultiPolygon feature per region with a boundary, keyed
    and propertied {id, name, slug, type, external_id, retired}, coordinates rounded to ~1 m.

    The get() lives on this un-cached base so CachedEndpointMixin.get() on
    RegionGeoJSON is the one dispatched to.
    """

    def get(self, request, *args, **kwargs):
        # Unfiltered this is every region in the database -- thousands of
        # square-mile sections among them -- so a type is required.
        region_type = request.GET.get('type', '').strip()
        if not region_type:
            return http.Http400({'error': 'The type parameter is required.'})
        if error := self.lookup_error():
            return error
        regions = (
            self.filter_queryset(self.get_queryset())
            .exclude(boundary=None).current_vintage().order_by('name')
        )
        if request.GET.get('simplify') == '1':
            if region_type not in shapes.SIMPLIFY_TYPES:
                return http.Http400({'error': 'simplify=1 is only supported for county, zipcode and tract.'})
            # The whole type is simplified together (shared borders stay
            # shared); the filters then pick from it.
            wanted = set(regions.values_list('sqid', flat=True))
            features = [f for f in shapes.simplified_features(region_type) if f['id'] in wanted]
        else:
            features = [shapes.region_feature(region, shapes.full_geometry(region)) for region in regions]
        return {'type': 'FeatureCollection', 'features': features}


class RegionGeoJSON(CachedEndpointMixin, RegionGeoJSONBase):
    """Regions as GeoJSON for a map: ?type= (required), plus ?slug=, ?name=, ?within=.
    ?simplify=1 returns shapes simplified together (for area maps)."""
    # Boundaries change only when an import runs; ?_cc=1 clears one early.
    cache_timeout = 60 * 60 * 24
    cache_key_version = 3

    def is_cacheable(self, response):
        # simplify=1's per-type shapes are already cached (compressed) by
        # shapes.simplified_features(); the per-request work above that is
        # only a set filter, so caching the assembled response here too
        # would just be a second, redundant copy of the same payload.
        if self.request.GET.get('simplify') == '1':
            return False
        return super().is_cacheable(response)


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    """One region with its boundary. ?buffer=1|3|5 widens the boundary by that many miles."""
    # Named by sqid: a retired region is still found.
    queryset = Region.all_objects.all()
    lookup_field = 'sqid'
    lookup_url_kwarg = 'region_id'

    def get(self, request, *args, **kwargs):
        miles, error = shapes.parse_buffer(request.GET)
        if error:
            return http.Http400({'error': error})
        response = super().get(request, *args, **kwargs)
        boundary = response['data'].get('boundary')
        if miles and boundary:
            shape = shapes.region_shape(self.object, miles)
            boundary['geometry'] = json.loads(shape.geojson)
            boundary['bbox'] = list(shape.extent)
        return response


class LocationList(generics.ListEndpoint):
    """
    Schools and child-care sites by official code: ?source= and ?external_id=
    (comma-separated), both required. A child-care site also answers to any of
    its other license numbers. Retired sites are included, flagged.
    """
    # Only ever a by-code lookup, never a full listing; all_objects so that
    # retired rows still resolve.
    queryset = Location.all_objects.all()
    serializer_class = LocationSerializer
    paginate = False

    def lookup_error(self):
        source = self.request.GET.get('source', '').strip()
        codes = parse_codes(self.request.GET.get('external_id', ''))
        if not source or not codes:
            return http.Http400({'error': 'The source and external_id parameters are required.'})
        if source not in SOURCES:
            return http.Http400({'error': f'Unknown source: {source}.'})
        if len(codes) > LOOKUP_MAX_CODES:
            return http.Http400({'error': f'At most {LOOKUP_MAX_CODES} codes can be looked up at once.'})
        return None

    def get(self, request, *args, **kwargs):
        return self.lookup_error() or super().get(request, *args, **kwargs)

    def get_queryset(self):
        codes = parse_codes(self.request.GET.get('external_id', ''))
        match = Q()
        for code in codes:
            match |= Q(external_id=code) | Q(metadata__facility_numbers__contains=[code])
        return (
            Location.all_objects
            .select_related('county', 'city', 'zipcode', 'school_district', 'replaced_by')
            .filter(source=self.request.GET.get('source', '').strip())
            .filter(match)
        )


class RegionMetaEndpoint(generics.Endpoint):
    """Metadata describing all region types supported by the API."""

    def get_counts(self):
        """Current regions per type: one grouped query, cached for an hour."""
        counts = cache.get(META_COUNT_CACHE_KEY)
        if counts is None:
            counts = dict(Region.objects.order_by().values_list('type').annotate(n=Count('pk')))
            cache.set(META_COUNT_CACHE_KEY, counts, META_COUNT_CACHE_TIMEOUT)
        return counts

    def get_types(self):
        payload = {}
        counts = self.get_counts()
        for region_type, label in Region.Type.choices:
            category = Region.TYPE_CATEGORIES[region_type]
            payload[region_type] = {
                'type': region_type,
                'label': label,
                'category': category.value,
                'count': counts.get(region_type, 0),
                'parents': Region.TYPE_PARENTS[region_type],
                'referenceable': region_type != Region.Type.LAND_USE,
                'browsable': region_type not in Region.NON_BROWSABLE_TYPES,
            }
        return payload

    def get(self, request, *args, **kwargs):
        return {'data': {
            'types': self.get_types(),
        }}


class PlaceSearch(generics.Endpoint):
    """Search regions by name, returning all high-confidence matches ordered by similarity.
    Accepts ?q=<name> and optional ?type=<type> to scope to a specific region type."""

    form_class = PlaceQueryForm

    def get(self, request):
        form = PlaceQueryForm(request.GET)
        form.is_valid()
        q = form.cleaned_data.get('q', '')
        region_type = form.cleaned_data.get('type', '')
        if not q:
            return {'data': []}
        regions = Region.objects.search_regions(q, type=region_type or None)
        return {'data': [RegionSerializer(r).serialize() for r in regions]}


class PointLookupForm(forms.Form):
    """The POST body of a point lookup. Error text never includes the input."""
    lat = forms.FloatField(min_value=-90, max_value=90, error_messages={
        'required': 'lat is required.',
        'invalid': 'lat must be a number between -90 and 90.',
        'min_value': 'lat must be a number between -90 and 90.',
        'max_value': 'lat must be a number between -90 and 90.',
    })
    lon = forms.FloatField(min_value=-180, max_value=180, error_messages={
        'required': 'lon is required.',
        'invalid': 'lon must be a number between -180 and 180.',
        'min_value': 'lon must be a number between -180 and 180.',
        'max_value': 'lon must be a number between -180 and 180.',
    })
    type = forms.CharField(required=False, strip=True)


@method_decorator(sensitive_post_parameters('lat', 'lon'), name='post')
class PlaceLookup(generics.Endpoint):
    """
    Resolve a name to the single best-match region (?q=, optional ?type=): without
    ?type, the best match among cities, then CDPs, then urban areas (the first of
    those types with a match); with it, the top match within that type.

    Or list the current regions containing a place: POST {lat, lon, type?} (the
    coordinates go in the body so they stay out of URLs and logs; they are
    rounded to 3 decimals), or GET ?monitor=<id>&type=. `type` is a
    comma-separated list; by default every type but land use and MTRS.
    """

    form_class = PlaceQueryForm

    def lookup_response(self, geometry, raw_types, key_for):
        try:
            types = parse_lookup_types(raw_types)
        except PlaceError as err:
            return http.Http400({'error': str(err)})
        return {'data': regions_containing(geometry, types, key_for(types))}

    def get(self, request):
        if 'lat' in request.GET or 'lon' in request.GET:
            return http.Http400({'error': 'Send coordinates in a POST body.'})
        form = PlaceQueryForm(request.GET)
        form.is_valid()
        q = form.cleaned_data.get('q', '')
        if request.GET.get('monitor', '').strip():
            if q:
                return http.Http400({'error': 'Give either q or monitor, not both.'})
            try:
                monitor = resolve_place({'monitor': request.GET['monitor']})
            except PlaceNotFound as err:
                return http.Http404({'error': str(err)})
            except PlaceError as err:
                return http.Http400({'error': str(err)})
            return self.lookup_response(
                monitor.position, request.GET.get('type', ''),
                lambda types: monitor_lookup_key(monitor, types))
        region_type = form.cleaned_data.get('type', '')
        region = Region.objects.resolve_place(q, type=region_type or None) if q else None
        return {'data': RegionSerializer(region).serialize() if region else None}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        if 'q' in body or 'monitor' in body:
            return http.Http400({'error': 'A POST takes lat and lon only.'})
        form = PointLookupForm(body)
        if not form.is_valid():
            # Messages only, never the values.
            errors = [error for field in form.errors.values() for error in field]
            return http.Http400({'error': ' '.join(errors)})
        lat, lon = round_point(form.cleaned_data['lat'], form.cleaned_data['lon'])
        return self.lookup_response(
            Point(lon, lat, srid=4326), form.cleaned_data['type'],
            lambda types: point_lookup_key(lat, lon, types))
