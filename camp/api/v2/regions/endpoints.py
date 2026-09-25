from django import forms

from resticus import generics, http

from camp.apps.regions import shapes
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin

from .filters import RegionFilter
from .serializers import RegionSerializer


class PlaceQueryForm(forms.Form):
    q = forms.CharField(required=False, strip=True)
    type = forms.CharField(required=False, strip=True)


class RegionMixin:
    model = Region
    serializer_class = RegionSerializer

    def get_queryset(self):
        return super().get_queryset().select_related('boundary')


class RegionList(RegionMixin, generics.ListEndpoint):
    filter_class = RegionFilter
    paginate = False

    def get_queryset(self):
        qs = super().get_queryset()
        within_ids = [value for value in self.request.GET.getlist('within') if value.strip()]
        if within_ids:
            geometry = Region.objects.filter(sqid__in=within_ids).combined_geometry()
            if geometry is None or geometry.empty:
                # `within` was asked for but nothing resolved (unknown ids, or
                # parents with no boundary): nothing can be inside it. Falling
                # back to the unnarrowed list here would silently hand back
                # every region in the database.
                return qs.none()
            qs = qs.contained_within(geometry)
        return qs


class RegionGeoJSONBase(RegionList):
    """
    The region list's filters, answered as a GeoJSON FeatureCollection for a
    map to draw: one MultiPolygon feature per region with a boundary, keyed
    and propertied {id, name, slug, type}, coordinates rounded to ~1 m.

    The get() lives on this un-cached base so CachedEndpointMixin.get() on
    RegionGeoJSON is the one dispatched to.
    """

    def get(self, request, *args, **kwargs):
        # Unfiltered this is every region in the database -- thousands of
        # square-mile sections among them -- so a type is required.
        region_type = request.GET.get('type', '').strip()
        if not region_type:
            return http.Http400({'error': 'The type parameter is required.'})
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
    cache_key_version = 2

    def is_cacheable(self, response):
        # simplify=1's per-type shapes are already cached (compressed) by
        # shapes.simplified_features(); the per-request work above that is
        # only a set filter, so caching the assembled response here too
        # would just be a second, redundant copy of the same payload.
        if self.request.GET.get('simplify') == '1':
            return False
        return super().is_cacheable(response)


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    lookup_field = 'sqid'
    lookup_url_kwarg = 'region_id'


class RegionMetaEndpoint(generics.Endpoint):
    """Metadata describing all region types supported by the API."""

    def get_types(self):
        payload = {}
        for region_type, label in Region.Type.choices:
            category = Region.TYPE_CATEGORIES[region_type]
            payload[region_type] = {
                'type': region_type,
                'label': label,
                'category': category.value,
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


class PlaceLookup(generics.Endpoint):
    """Resolve a name to the single best-match region. Without ?type, resolves to the
    containing Place using City/CDP fallback. With ?type=<type>, returns the top match
    within that type directly."""

    form_class = PlaceQueryForm

    def get(self, request):
        form = PlaceQueryForm(request.GET)
        form.is_valid()
        q = form.cleaned_data.get('q', '')
        region_type = form.cleaned_data.get('type', '')
        region = Region.objects.resolve_place(q, type=region_type or None) if q else None
        return {'data': RegionSerializer(region).serialize() if region else None}
