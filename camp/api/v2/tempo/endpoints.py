from django.http import Http404
from django.utils.functional import cached_property

from resticus import generics
from resticus.http import Http400

from camp.apps.regions.models import Region
from camp.apps.tempo.models import Granule
from camp.apps.tempo.queries import point_series, region_series
from camp.apps.tempo.rendering import PRODUCT_COLOR_RANGES, _level_set_for

from .filters import GranuleFilter, default_to_today
from .forms import TempoPointForm, TempoSeriesForm
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


class TempoPoint(TempoProductMixin, generics.Endpoint):
    """Point value series for one product across an hourly timestamp range."""

    def get(self, request, *args, **kwargs):
        form = TempoPointForm(request.GET)
        if not form.is_valid():
            return Http400({'errors': form.errors.get_json_data()})

        start, end = form.cleaned_data['start'], form.cleaned_data['end']
        if start is None:
            queryset = default_to_today(Granule.objects.filter(product=self.product))
            timestamps = queryset.values_list('timestamp', flat=True)
            if not timestamps:
                return []
            start, end = min(timestamps), max(timestamps)

        return point_series(self.product, form.point, start, end)


class TempoRegion(TempoProductMixin, generics.Endpoint):
    """Zonal-aggregate value series over a community boundary, for one product across an hourly timestamp range."""

    def get(self, request, region_id, *args, **kwargs):
        try:
            region = Region.objects.select_related('boundary').get(sqid=region_id)
            geometry = region.boundary.geometry
        except (Region.DoesNotExist, AttributeError):
            raise Http404(f'"{region_id}" is not a valid region id')

        form = TempoSeriesForm(request.GET)
        if not form.is_valid():
            return Http400({'errors': form.errors.get_json_data()})

        start, end = form.cleaned_data['start'], form.cleaned_data['end']
        if start is None:
            queryset = default_to_today(Granule.objects.filter(product=self.product))
            timestamps = queryset.values_list('timestamp', flat=True)
            if not timestamps:
                return []
            start, end = min(timestamps), max(timestamps)

        return region_series(self.product, geometry, start, end)
