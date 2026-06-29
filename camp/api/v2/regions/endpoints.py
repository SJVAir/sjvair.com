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


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'region_id'


class PlaceSearch(generics.Endpoint):
    """Search regions by name, returning all high-confidence matches ordered by similarity.
    Accepts ?q=<name> and optional ?type=<type> to scope to a specific region type."""

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

    def get(self, request):
        form = PlaceQueryForm(request.GET)
        form.is_valid()
        q = form.cleaned_data.get('q', '')
        region_type = form.cleaned_data.get('type', '')
        region = Region.objects.resolve_place(q, type=region_type or None) if q else None
        return {'data': RegionSerializer(region).serialize() if region else None}
