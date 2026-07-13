from django.test import TestCase
from django.urls import reverse


class TempoProductsTests(TestCase):
    # TempoProducts is a plain generics.Endpoint (not ListEndpoint), so its
    # get() return value is JSON-encoded as-is by resticus's Http200 -- no
    # {"data": ...} envelope. That envelope only comes from
    # ListModelMixin/DetailModelMixin, which this endpoint doesn't use.
    def test_lists_three_user_facing_products_excluding_cldo4(self):
        response = self.client.get(reverse('api:v2:tempo:product-list'))

        assert response.status_code == 200
        keys = {product['key'] for product in response.json()}
        assert keys == {'no2', 'o3tot', 'hcho'}

    def test_each_product_has_label_units_and_legend(self):
        response = self.client.get(reverse('api:v2:tempo:product-list'))

        no2 = next(p for p in response.json() if p['key'] == 'no2')
        assert no2['label'] == 'Nitrogen Dioxide'
        assert no2['units'] == 'molecules/cm²'
        assert len(no2['legend']) == 6
        assert set(no2['legend'][0].keys()) == {'value', 'label', 'color'}
