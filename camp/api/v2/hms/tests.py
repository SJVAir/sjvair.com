from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke
from camp.apps.regions.models import Boundary, Region


SJV_POLYGON = (
    'POLYGON(('
    '-119.860839 36.660399, '
    '-119.860839 36.905755, '
    '-119.650879 36.905755, '
    '-119.650879 36.660399, '
    '-119.860839 36.660399'
    '))'
)
SJV_POINT = 'POINT(-119.069180 36.965302)'


def _today():
    return timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()


def create_smoke(density='light', days_offset=0):
    today = _today()
    baseline = datetime.combine(today, time(12, 0, tzinfo=dt_timezone.utc))
    smoke = Smoke(
        date=today + timedelta(days=days_offset),
        satellite='TestSatellite',
        density=density,
        start=baseline - timedelta(hours=2),
        end=baseline + timedelta(hours=2),
        geometry=MultiPolygon(GEOSGeometry(SJV_POLYGON, srid=4326)),
    )
    smoke.full_clean()
    smoke.save()
    return smoke


def create_fire(days_offset=0):
    today = _today()
    baseline = datetime.combine(today, time(12, 0, tzinfo=dt_timezone.utc))
    fire = Fire(
        date=today + timedelta(days=days_offset),
        satellite='TestSatellite',
        timestamp=baseline,
        frp='294.207',
        ecosystem=22,
        method='FDC',
        geometry=GEOSGeometry(SJV_POINT, srid=4326),
    )
    fire.full_clean()
    fire.save()
    return fire


class SmokeListTests(TestCase):
    def setUp(self):
        self.smoke_today = create_smoke('light')
        self.smoke_yesterday = create_smoke('medium', days_offset=-1)

    def test_defaults_to_today(self):
        url = reverse('api:v2:hms:smoke-list')
        response = self.client.get(url)
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert str(self.smoke_today.pk) in ids
        assert str(self.smoke_yesterday.pk) not in ids

    def test_date_filter(self):
        url = reverse('api:v2:hms:smoke-list')
        response = self.client.get(url, {'date': self.smoke_yesterday.date})
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert str(self.smoke_yesterday.pk) in ids
        assert str(self.smoke_today.pk) not in ids

    def test_density_filter(self):
        url = reverse('api:v2:hms:smoke-list')
        response = self.client.get(url, {'density__iexact': 'LIGHT'})
        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['id'] == str(self.smoke_today.pk)


class SmokeDetailTests(TestCase):
    def setUp(self):
        self.smoke = create_smoke()

    def test_detail(self):
        url = reverse('api:v2:hms:smoke-detail', kwargs={'smoke_id': self.smoke.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['data']['id'] == str(self.smoke.pk)

    def test_detail_not_found(self):
        url = reverse('api:v2:hms:smoke-detail', kwargs={'smoke_id': 'gQ7rC18FRKuu15z9m2CsFm'})
        response = self.client.get(url)
        assert response.status_code == 404


class FireListTests(TestCase):
    def setUp(self):
        self.fire_today = create_fire()
        self.fire_yesterday = create_fire(days_offset=-1)

    def test_defaults_to_today(self):
        url = reverse('api:v2:hms:fire-list')
        response = self.client.get(url)
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert str(self.fire_today.pk) in ids
        assert str(self.fire_yesterday.pk) not in ids

    def test_date_filter(self):
        url = reverse('api:v2:hms:fire-list')
        response = self.client.get(url, {'date': self.fire_yesterday.date})
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert str(self.fire_yesterday.pk) in ids
        assert str(self.fire_today.pk) not in ids

    def test_method_filter(self):
        url = reverse('api:v2:hms:fire-list')
        response = self.client.get(url, {'method__iexact': 'FDC'})
        assert response.status_code == 200
        assert len(response.json()['data']) == 1


class FireDetailTests(TestCase):
    def setUp(self):
        self.fire = create_fire()

    def test_detail(self):
        url = reverse('api:v2:hms:fire-detail', kwargs={'fire_id': self.fire.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['data']['id'] == str(self.fire.pk)

    def test_detail_not_found(self):
        url = reverse('api:v2:hms:fire-detail', kwargs={'fire_id': 'gQ7rC18FRKuu15z9m2CsFm'})
        response = self.client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Region filter helpers
# ---------------------------------------------------------------------------

# SJV_POLYGON spans lon -119.861 to -119.651, lat 36.660 to 36.906
# SJV_POINT is at lon -119.069, lat 36.965 (east of SJV_POLYGON)
REGION_COVERS_SMOKE = 'MULTIPOLYGON (((-120.0 36.5, -119.5 36.5, -119.5 37.0, -120.0 37.0, -120.0 36.5)))'
REGION_MISSES_SMOKE = 'MULTIPOLYGON (((-118.5 36.5, -118.0 36.5, -118.0 37.0, -118.5 37.0, -118.5 36.5)))'
REGION_COVERS_FIRE = 'MULTIPOLYGON (((-119.5 36.7, -118.9 36.7, -118.9 37.2, -119.5 37.2, -119.5 36.7)))'
REGION_MISSES_FIRE = 'MULTIPOLYGON (((-121.0 37.5, -120.5 37.5, -120.5 38.0, -121.0 38.0, -121.0 37.5)))'


def create_region(geometry_wkt=None, slug='test-region', external_id='9001'):
    region = Region.objects.create(
        name='Test Region', slug=slug, type=Region.Type.CITY, external_id=external_id,
    )
    if geometry_wkt:
        boundary = Boundary.objects.create(
            region=region, version='2020',
            geometry=GEOSGeometry(geometry_wkt, srid=4326),
        )
        region.boundary = boundary
        region.save()
    return region


# ---------------------------------------------------------------------------
# Smoke region_id filter
# ---------------------------------------------------------------------------

class SmokeRegionFilterTests(TestCase):
    def setUp(self):
        self.smoke = create_smoke()
        self.url = reverse('api:v2:hms:smoke-list')

    def test_region_intersecting_smoke_returns_it(self):
        region = create_region(REGION_COVERS_SMOKE)
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        ids = [r['id'] for r in data['data']]
        assert str(self.smoke.pk) in ids

    def test_region_not_intersecting_smoke_excludes_it(self):
        region = create_region(REGION_MISSES_SMOKE, slug='far-region', external_id='9002')
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        assert len(data['data']) == 0

    def test_region_without_boundary_returns_empty(self):
        region = create_region(slug='no-boundary', external_id='9003')
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        assert len(data['data']) == 0

    def test_invalid_region_id_returns_empty(self):
        data = self.client.get(self.url, {'region_id': 'BOGUS'}).json()
        assert len(data['data']) == 0


# ---------------------------------------------------------------------------
# Fire region_id filter
# ---------------------------------------------------------------------------

class FireRegionFilterTests(TestCase):
    def setUp(self):
        self.fire = create_fire()
        self.url = reverse('api:v2:hms:fire-list')

    def test_region_containing_fire_returns_it(self):
        region = create_region(REGION_COVERS_FIRE)
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        ids = [r['id'] for r in data['data']]
        assert str(self.fire.pk) in ids

    def test_region_not_containing_fire_excludes_it(self):
        region = create_region(REGION_MISSES_FIRE, slug='far-region', external_id='9002')
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        assert len(data['data']) == 0

    def test_region_without_boundary_returns_empty(self):
        region = create_region(slug='no-boundary', external_id='9003')
        data = self.client.get(self.url, {'region_id': region.sqid}).json()
        assert len(data['data']) == 0

    def test_invalid_region_id_returns_empty(self):
        data = self.client.get(self.url, {'region_id': 'BOGUS'}).json()
        assert len(data['data']) == 0
