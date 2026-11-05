from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke
from camp.apps.hms.place import smoke_days
from camp.apps.monitors.cimis.models import CIMIS
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


class HMSMetaTests(TestCase):
    def get_scales(self):
        response = self.client.get(reverse('api:v2:hms:hms-meta'))
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=3600'
        return response.json()['data']['scales']

    def test_hms_meta_smoke_opacity(self):
        smoke = self.get_scales()['smoke-density']
        assert smoke['label'] == 'Smoke Density'
        heavy = smoke['levels'][2]
        assert heavy['key'] == 'heavy'
        assert heavy['opacity'] == 0.4
        assert heavy['tier'] == 3

    def test_hms_meta_fire_tierless(self):
        fire = self.get_scales()['fire-frp']
        assert fire['label'] == 'Fire Radiative Power'
        assert fire['units'] == 'MW'
        assert all(level['tier'] is None for level in fire['levels'])
        assert fire['levels'][-1]['max'] is None
        assert fire['levels'][0]['min'] == 0


class DateRangeTestsMixin:
    """Ranges given as date__gte/date__lte, without an exact date."""
    url_name = None
    create = None

    def setUp(self):
        self.records = {offset: type(self).create(days_offset=offset) for offset in (-3, -2, -1, 0)}

    def day(self, offset):
        return (_today() + timedelta(days=offset)).isoformat()

    def ids(self, params):
        response = self.client.get(reverse(self.url_name), params)
        assert response.status_code == 200
        return {r['id'] for r in response.json()['data']}

    def expected(self, *offsets):
        return {str(self.records[offset].pk) for offset in offsets}

    def test_date_range_without_date(self):
        ids = self.ids({'date__gte': self.day(-3), 'date__lte': self.day(-1)})
        assert ids == self.expected(-3, -2, -1)

    def test_open_ended_range(self):
        ids = self.ids({'date__gte': self.day(-2)})
        assert ids == self.expected(-2, -1, 0)

    def test_empty_date_with_range(self):
        ids = self.ids({'date': '', 'date__gte': self.day(-3), 'date__lte': self.day(-1)})
        assert ids == self.expected(-3, -2, -1)

    def test_no_date_params_defaults_to_today(self):
        assert self.ids({}) == self.expected(0)


class SmokeDateRangeTests(DateRangeTestsMixin, TestCase):
    url_name = 'api:v2:hms:smoke-list'
    create = staticmethod(create_smoke)


class FireDateRangeTests(DateRangeTestsMixin, TestCase):
    url_name = 'api:v2:hms:fire-list'
    create = staticmethod(create_fire)


class PagingOrderTestsMixin:
    """Pages of one day's rows must not repeat or skip rows: the order needs a unique tiebreaker."""
    url_name = None
    create = None
    list_view = None

    def test_order_has_a_unique_tiebreaker(self):
        ordering = self.list_view().get_queryset().query.order_by
        assert ordering[-1] in ('id', 'pk', '-id', '-pk'), ordering

    def test_pages_of_one_day_are_complete(self):
        made = {str(type(self).create().pk) for _ in range(105)}
        seen = []
        for page in (1, 2):
            response = self.client.get(reverse(self.url_name), {'page': page})
            seen += [r['id'] for r in response.json()['data']]
        assert len(seen) == len(set(seen)) == 105
        assert set(seen) == made


class SmokePagingOrderTests(PagingOrderTestsMixin, TestCase):
    url_name = 'api:v2:hms:smoke-list'
    create = staticmethod(create_smoke)

    def list_view(self):
        from camp.api.v2.hms.endpoints import SmokeList
        view = SmokeList()
        view.request = type('R', (), {'GET': {}})()
        return view


class FirePagingOrderTests(PagingOrderTestsMixin, TestCase):
    url_name = 'api:v2:hms:fire-list'
    create = staticmethod(create_fire)

    def list_view(self):
        from camp.api.v2.hms.endpoints import FireList
        view = FireList()
        view.request = type('R', (), {'GET': {}})()
        return view


# ---------------------------------------------------------------------------
# smoke/place/
# ---------------------------------------------------------------------------

PD = date(2026, 6, 1)
NOW = datetime(2026, 7, 12, 10, 0, tzinfo=ZoneInfo('America/Los_Angeles'))


def create_day_smoke(day, density='light', wkt=SJV_POLYGON):
    baseline = datetime.combine(day, time(12, 0, tzinfo=dt_timezone.utc))
    return Smoke.objects.create(
        date=day, satellite='TestSatellite', density=density,
        start=baseline - timedelta(hours=2), end=baseline + timedelta(hours=2),
        geometry=MultiPolygon(GEOSGeometry(wkt, srid=4326)),
    )


class SmokePlaceTests(TestCase):
    fixtures = ['regions']

    def setUp(self):
        cache.clear()
        self.url = reverse('api:v2:hms:smoke-place')
        self.region = create_region(REGION_COVERS_SMOKE)
        patcher = patch.object(timezone, 'now', return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, region=None, **params):
        region = region or self.region
        return self.client.get(self.url, {
            'region_type': region.type, 'region': region.external_id, **params})

    def days(self, region=None, **params):
        return self.get(region, **params).json()['data']['days']

    def test_route_not_shadowed_by_detail(self):
        assert self.url == '/api/2.0/hms/smoke/place/'
        response = self.client.get(self.url, {'region_type': 'county', 'region': '06019'})
        assert response.status_code == 200

    def test_existing_smoke_detail_still_routes(self):
        smoke = create_smoke()
        assert self.client.get(reverse('api:v2:hms:smoke-detail', args=[smoke.pk])).status_code == 200

    def test_region_days_shape_and_place(self):
        create_day_smoke(PD)
        body = self.get(date__gte=PD, date__lte=PD + timedelta(days=1)).json()['data']
        assert body['place'] == {'region': {'type': 'city', 'external_id': '9001', 'name': 'Test Region'}}
        assert [d['date'] for d in body['days']] == ['2026-06-01', '2026-06-02']
        assert body['days'][0]['density'] == 'light'
        assert body['days'][1]['density'] is None
        assert set(body['days'][0]['coverage']) == {'light', 'medium', 'heavy'}

    def test_monitor_place(self):
        create_day_smoke(PD, 'medium')
        monitor = CIMIS.objects.create(
            name='In', station_number='7', position=Point(-119.75, 36.8, srid=4326),
            location=CIMIS.LOCATION.outside)
        body = self.client.get(self.url, {'monitor': monitor.pk, 'date__gte': PD, 'date__lte': PD}).json()['data']
        assert body['place'] == {'monitor': str(monitor.pk)}
        assert body['days'][0]['coverage'] == {'light': 1.0, 'medium': 1.0, 'heavy': 0.0}

    def test_default_range_is_last_30_days(self):
        days = self.days()
        assert len(days) == 30
        assert days[0]['date'] == '2026-06-13' and days[-1]['date'] == '2026-07-12'

    def test_blank_dates_are_absent(self):
        assert len(self.days(date__gte='', date__lte='')) == 30

    def test_only_gte_runs_through_today(self):
        days = self.days(date__gte='2026-07-10')
        assert [d['date'] for d in days] == ['2026-07-10', '2026-07-11', '2026-07-12']

    def test_only_lte_is_30_days_ending_there(self):
        days = self.days(date__lte='2026-03-31')
        assert len(days) == 30
        assert days[0]['date'] == '2026-03-02' and days[-1]['date'] == '2026-03-31'

    def test_bad_ranges_are_400_no_cache(self):
        for params in ({'date__gte': '2026-07-02', 'date__lte': '2026-07-01'},
                       {'date__gte': '2025-01-01', 'date__lte': '2026-01-02'},
                       {'date__gte': 'nope'}):
            response = self.get(**params)
            assert response.status_code == 400
            assert 'error' in response.json() or 'errors' in response.json()
            assert 'no-cache' in response['Cache-Control']

    def test_366_days_allowed(self):
        assert len(self.days(date__gte='2025-01-01', date__lte='2026-01-01')) == 366

    def test_place_errors_pass_through(self):
        for params, status in (
            ({'region_type': 'land_use', 'region': '1'}, 400),
            ({'region_type': 'county', 'region': 'nope'}, 404),
            ({}, 400),
        ):
            response = self.client.get(self.url, params)
            assert response.status_code == status
            assert 'no-cache' in response['Cache-Control']
        hidden = CIMIS.objects.create(
            name='Hidden', station_number='8', position=Point(-119.75, 36.8, srid=4326),
            location=CIMIS.LOCATION.outside, is_hidden=True)
        response = self.client.get(self.url, {'monitor': hidden.pk})
        assert response.status_code == 404
        assert 'no-cache' in response['Cache-Control']

    def test_region_without_boundary_is_all_null(self):
        region = create_region(slug='no-boundary', external_id='9003')
        assert self.days(region, date__gte=PD, date__lte=PD) == [
            {'date': '2026-06-01', 'density': None, 'coverage': {'light': 0.0, 'medium': 0.0, 'heavy': 0.0}}]

    def test_settled_range_cached_long(self):
        response = self.get(date__gte=PD, date__lte=PD)
        assert response['Cache-Control'] == 'public, max-age=86400'

    def test_range_touching_today_cached_short(self):
        assert self.get()['Cache-Control'] == 'public, max-age=900'

    def test_future_days_filled_with_null(self):
        days = self.days(date__gte='2026-07-12', date__lte='2026-07-14')
        assert len(days) == 3 and days[-1]['density'] is None

    def test_settled_answer_cached_server_side(self):
        with patch('camp.api.v2.hms.endpoints.smoke_days', wraps=smoke_days) as spy:
            self.get(date__gte=PD, date__lte=PD)
            self.get(date__gte=PD, date__lte=PD)
        assert spy.call_count == 1

    def test_unsettled_answer_not_cached_server_side(self):
        with patch('camp.api.v2.hms.endpoints.smoke_days', wraps=smoke_days) as spy:
            self.get()
            self.get()
        assert spy.call_count == 2

    def test_retired_region_still_answers(self):
        self.region.retired_at = timezone.now()
        self.region.save()
        assert self.get(date__gte=PD, date__lte=PD).status_code == 200
