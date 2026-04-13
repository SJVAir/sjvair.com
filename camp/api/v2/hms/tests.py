from datetime import date, datetime, time, timedelta

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke


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


def create_smoke(density='light', days_offset=0):
    today = timezone.now().date()
    baseline = datetime.combine(today, time(12, 0, tzinfo=timezone.utc))
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
    today = timezone.now().date()
    baseline = datetime.combine(today, time(12, 0, tzinfo=timezone.utc))
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
