from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import numpy as np
from django.conf import settings
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.regions.models import Boundary, Region
from camp.apps.tempo.models import Granule
from camp.apps.tempo.raster import build_raster
from camp.utils.datetime import localtime, make_aware


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

    @patch('camp.api.v2.tempo.filters.localtime')
    def test_falls_back_to_yesterday_when_todays_data_does_not_match_filter(self, mock_localtime):
        # Regression test for a real bug: default_to_today used to decide
        # whether to fall back to yesterday by checking existence *before*
        # is_final/version filters were applied, so "today has *some* data
        # (just not final)" incorrectly suppressed the fallback even though
        # yesterday had exactly what was requested. Pins the clock to 1am LA
        # (before-noon) so this is deterministic, not dependent on the test
        # happening to run near real LA midnight.
        today = localtime().date()
        yesterday = today - timedelta(days=1)
        mock_localtime.return_value = make_aware(
            datetime.combine(today, datetime.min.time()).replace(hour=1),
            tz=settings.DEFAULT_TIMEZONE,
        )

        create_granule(
            timestamp=make_aware(datetime.combine(today, datetime.min.time()).replace(hour=0, minute=30), tz=settings.DEFAULT_TIMEZONE),
            is_final=False,
        )
        final_granule = create_granule(
            timestamp=make_aware(datetime.combine(yesterday, datetime.min.time()).replace(hour=20), tz=settings.DEFAULT_TIMEZONE),
            is_final=True,
        )

        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['no2']), {'is_final': 'true'})

        sqids = {row['sqid'] for row in response.json()['data']}
        assert sqids == {final_granule.sqid}

    def test_unknown_product_404s(self):
        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['not-a-real-product']))

        assert response.status_code == 404

    def test_excludes_other_products(self):
        no2_granule = create_granule(product='no2')
        create_granule(product='hcho')

        response = self.client.get(reverse('api:v2:tempo:granule-list', args=['no2']))

        sqids = {row['sqid'] for row in response.json()['data']}
        assert sqids == {no2_granule.sqid}


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

    def test_defaults_to_todays_granule_when_no_range_given(self):
        today_granule = create_granule()
        create_granule(timestamp=timezone.now() - timedelta(days=3))

        response = self.client.get(reverse('api:v2:tempo:point-list', args=['no2']), {
            'latitude': '36.5', 'longitude': '-119.5',
        })

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['value'] == 1.0
        assert data[0]['timestamp'] == today_granule.timestamp.isoformat().replace('+00:00', 'Z')

    def test_empty_list_when_no_range_given_and_no_granules_exist(self):
        response = self.client.get(reverse('api:v2:tempo:point-list', args=['no2']), {
            'latitude': '36.5', 'longitude': '-119.5',
        })

        assert response.status_code == 200
        assert response.json() == []


def create_region_with_boundary(polygon):
    # Boundary.geometry is a MultiPolygonField, not PolygonField -- must wrap.
    # Region.boundary (the OneToOneField HMS's filter_region_id and this
    # endpoint both read via region.boundary.geometry) is a separate pointer
    # from Boundary.region (the reverse FK) and isn't set automatically by
    # creating a Boundary row -- it has to be assigned explicitly.
    region = Region.objects.create(name='Test Region', slug='test-region', type=Region.Type.COUNTY)
    boundary = Boundary.objects.create(region=region, geometry=MultiPolygon(polygon), version='2026')
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


class TempoRegionTests(TestCase):
    # TempoRegion is a plain generics.Endpoint like TempoProducts/TempoPoint
    # -- no {"data": ...} envelope, response.json() is the bare list.
    def test_returns_series_for_explicit_range(self):
        region = create_region_with_boundary(Polygon.from_bbox((-120, 36, -119, 37)))
        ts0 = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        ts1 = ts0 + timedelta(hours=1)
        create_granule(timestamp=ts0)
        create_granule(timestamp=ts1)

        response = self.client.get(
            reverse('api:v2:tempo:region-list', args=['no2', region.sqid]),
            {'start': ts0.isoformat(), 'end': ts1.isoformat()},
        )

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_unknown_region_404s(self):
        response = self.client.get(reverse('api:v2:tempo:region-list', args=['no2', 'not-a-real-region']))

        assert response.status_code == 404

    def test_unknown_product_404s(self):
        region = create_region_with_boundary(Polygon.from_bbox((-120, 36, -119, 37)))

        response = self.client.get(reverse('api:v2:tempo:region-list', args=['not-a-real-product', region.sqid]))

        assert response.status_code == 404

    def test_region_without_boundary_404s(self):
        region = Region.objects.create(name='No Boundary', slug='no-boundary', type=Region.Type.COUNTY)

        response = self.client.get(reverse('api:v2:tempo:region-list', args=['no2', region.sqid]))

        assert response.status_code == 404

    def test_range_over_cap_is_400(self):
        region = create_region_with_boundary(Polygon.from_bbox((-120, 36, -119, 37)))
        now = timezone.now()

        response = self.client.get(
            reverse('api:v2:tempo:region-list', args=['no2', region.sqid]),
            {'start': (now - timedelta(days=91)).isoformat(), 'end': now.isoformat()},
        )

        assert response.status_code == 400

    def test_defaults_to_todays_granule_when_no_range_given(self):
        region = create_region_with_boundary(Polygon.from_bbox((-120, 36, -119, 37)))
        today_granule = create_granule()
        create_granule(timestamp=timezone.now() - timedelta(days=3))

        response = self.client.get(reverse('api:v2:tempo:region-list', args=['no2', region.sqid]))

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['timestamp'] == today_granule.timestamp.isoformat().replace('+00:00', 'Z')

    def test_empty_list_when_no_range_given_and_no_granules_exist(self):
        region = create_region_with_boundary(Polygon.from_bbox((-120, 36, -119, 37)))

        response = self.client.get(reverse('api:v2:tempo:region-list', args=['no2', region.sqid]))

        assert response.status_code == 200
        assert response.json() == []
