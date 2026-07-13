from django.http import Http404
from django.utils.functional import cached_property

from resticus import generics

from camp.apps.tempo.models import Granule
from camp.apps.tempo.rendering import PRODUCT_COLOR_RANGES, _level_set_for

from .filters import GranuleFilter, default_to_today
from .serializers import GranuleSerializer

PRODUCT_UNITS = {
    'no2': 'molecules/cm²',
    'o3tot': 'molecules/cm²',
    'hcho': 'molecules/cm²',
}


class TempoProducts(generics.Endpoint):
    """User-facing TEMPO product metadata: label, units, and legend color stops. Excludes cldo4 (QA-only, not a toggleable map layer)."""

    def get(self, request):
        products = []
        for key, label in Granule.Product.choices:
            if key not in PRODUCT_COLOR_RANGES or key not in PRODUCT_UNITS:
                continue  # cldo4 has a color range for preview rendering but no units/legend -- not user-facing
            levels = _level_set_for(key)
            products.append({
                'key': key,
                'label': str(label),
                'units': PRODUCT_UNITS[key],
                'legend': [
                    {'value': level.value, 'label': str(level.label), 'color': level.color}
                    for level in levels
                ],
            })
        return products


class TempoProductMixin:
    @cached_property
    def product(self):
        product = self.kwargs['product']
        if product not in Granule.Product.values:
            raise Http404(f'"{product}" is not a valid TEMPO product')
        return product


class GranuleMixin(TempoProductMixin):
    model = Granule
    serializer_class = GranuleSerializer
    paginate = True

    def get_queryset(self):
        return Granule.objects.filter(product=self.product)


class GranuleList(GranuleMixin, generics.ListEndpoint):
    """List TEMPO granules for one product. Defaults to today's granules, falling back to yesterday before noon if today's data isn't available yet."""

    filter_class = GranuleFilter

    def get_queryset(self):
        queryset = super().get_queryset()
        if 'date' not in self.request.GET and 'timestamp' not in self.request.GET:
            return default_to_today(queryset)
        return queryset


class GranuleLatest(GranuleMixin, generics.DetailEndpoint):
    """The single most recent Granule for one product -- for the map's default overlay load."""

    def get_object(self):
        granule = default_to_today(self.get_queryset()).first()  # Granule.Meta.ordering = ('-timestamp',)
        if granule is None:
            raise Http404('No TEMPO data available yet for this product.')
        return granule
