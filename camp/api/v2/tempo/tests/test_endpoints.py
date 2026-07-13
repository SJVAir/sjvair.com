from datetime import datetime, timedelta, timezone as dt_timezone

import numpy as np
from django.contrib.gis.geos import Polygon
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.tempo.models import Granule
from camp.apps.tempo.raster import build_raster


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


def create_granule(product='no2', timestamp=None, is_final=False, version='V03'):
    timestamp = timestamp or timezone.now().replace(minute=0, second=0, microsecond=0)
    raster = build_raster(np.array([[1.0]]), lon_min=-120, lat_min=36, lon_max=-119, lat_max=37)
    bounds = Polygon.from_bbox((-120, 36, -119, 37))
    bounds.srid = 4326
    return Granule.objects.create(
        product=product, timestamp=timestamp, version=version,
        is_final=is_final, raster=raster, bounds=bounds,
    )


class GranuleListTests(TestCase):
    def test_defaults_to_todays_granules(self):
        today_granule = create_granule()
        create_granule(timestamp=timezone.now() - timedelta(days=3))

        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['no2']))

        assert response.status_code == 200
        sqids = {row['sqid'] for row in response.json()['data']}
        assert sqids == {today_granule.sqid}

    def test_filters_by_is_final(self):
        create_granule(is_final=False)
        final_granule = create_granule(timestamp=timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1), is_final=True)

        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['no2']), {'is_final': 'true'})

        sqids = {row['sqid'] for row in response.json()['data']}
        assert sqids == {final_granule.sqid}

    def test_unknown_product_404s(self):
        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['not-a-real-product']))

        assert response.status_code == 404

    def test_excludes_other_products(self):
        create_granule(product='no2')
        create_granule(product='hcho')

        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['no2']))

        assert all(row['product'] == 'no2' if 'product' in row else True for row in response.json()['data'])
        assert len(response.json()['data']) == 1


class GranuleLatestTests(TestCase):
    def test_returns_most_recent_granule_as_single_object_not_a_list(self):
        older = create_granule(timestamp=timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2))
        newest = create_granule(timestamp=timezone.now().replace(minute=0, second=0, microsecond=0))

        response = self.client.get(reverse('api:v2:tempo:granule-latest', args=['no2']))

        assert response.status_code == 200
        assert response.json()['data']['sqid'] == newest.sqid

    def test_404s_when_nothing_ingested_yet(self):
        response = self.client.get(reverse('api:v2:tempo:granule-latest', args=['no2']))

        assert response.status_code == 404

    def test_unknown_product_404s(self):
        response = self.client.get(reverse('api:v2:tempo:granule-latest', args=['not-a-real-product']))

        assert response.status_code == 404


class TempoPointTests(TestCase):
    # TempoPoint is a plain generics.Endpoint like TempoProducts above -- no
    # {"data": ...} envelope, response.json() is the bare list.
    def test_returns_series_for_explicit_range(self):
        ts0 = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        ts1 = ts0 + timedelta(hours=1)
        create_granule(timestamp=ts0)
        create_granule(timestamp=ts1)

        response = self.client.get(reverse('api:v2:tempo:point-list', args=['no2']), {
            'latitude': '36.5', 'longitude': '-119.5',
            'start': ts0.isoformat(), 'end': ts1.isoformat(),
        })

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_missing_lat_lon_is_400(self):
        response = self.client.get(reverse('api:v2:tempo:point-list', args=['no2']))

        assert response.status_code == 400

    def test_range_over_cap_is_400(self):
        now = timezone.now()
        response = self.client.get(reverse('api:v2:tempo:point-list', args=['no2']), {
            'latitude': '36.5', 'longitude': '-119.5',
            'start': (now - timedelta(days=91)).isoformat(), 'end': now.isoformat(),
        })

        assert response.status_code == 400
