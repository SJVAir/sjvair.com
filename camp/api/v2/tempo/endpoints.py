from resticus import generics

from camp.apps.tempo.models import Granule
from camp.apps.tempo.rendering import PRODUCT_COLOR_RANGES, _level_set_for

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
