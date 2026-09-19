from django import forms

from resticus import generics

from camp.apps.regions.models import Region

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
        within_ids = self.request.GET.getlist('within')
        if within_ids:
            geometry = Region.objects.filter(sqid__in=within_ids).combined_geometry()
            if geometry:
                qs = qs.contained_within(geometry)
        return qs


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
