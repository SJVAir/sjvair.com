from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from camp.apps.forecasts.models import Forecast
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.regions.models import Region
from camp.apps.regions.tests.test_resolve import make_region
from camp.utils.datetime import localtime


def create_forecast(region, forecast_date, issued_date=None, aqi_value=101,
                     pollutant=Forecast.Pollutant.OZONE, air_alert=False):
    issued_date = issued_date or forecast_date
    return Forecast.objects.create(
        region=region,
        zone_name=region.name.replace(' County', ''),
        forecast_date=forecast_date,
        issued_date=issued_date,
        published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
        aqi_value=aqi_value,
        aqi_category='Unhealthy for Sensitive Groups',
        pollutant=pollutant,
        burn_status='Discouraged',
        burn_status_text='Discouraged: Burning Discouraged',
        air_alert=air_alert,
    )


class ForecastListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(name='Fresno County')
        self.kern = Region.objects.get(name='Kern County')
        self.today = localtime().date()
        self.yesterday = self.today - timedelta(days=1)
        self.tomorrow = self.today + timedelta(days=1)
        self.forecast_today = create_forecast(self.fresno, self.today)
        self.forecast_tomorrow = create_forecast(self.fresno, self.tomorrow, issued_date=self.today)
        self.forecast_yesterday = create_forecast(self.kern, self.yesterday, issued_date=self.yesterday)
        self.url = reverse('api:v2:forecasts:forecast-list')

    def test_defaults_to_today_and_future(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_today.sqid in ids
        assert self.forecast_tomorrow.sqid in ids
        assert self.forecast_yesterday.sqid not in ids

    def test_forecast_date_filter_overrides_default(self):
        response = self.client.get(self.url, {'forecast_date': self.yesterday.isoformat()})
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_yesterday.sqid in ids
        assert self.forecast_today.sqid not in ids

    def test_region_id_filter(self):
        response = self.client.get(self.url, {
            'region_id': self.kern.sqid,
            'forecast_date__gte': self.yesterday.isoformat(),
        })
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_yesterday.sqid in ids
        assert self.forecast_today.sqid not in ids

    def test_list_has_no_boundary(self):
        row = self.client.get(self.url).json()['data'][0]
        assert 'boundary' not in row['region']
        assert set(row['region']) == {'id', 'type', 'external_id', 'name'}


class ForecastDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(name='Fresno County')
        self.forecast = create_forecast(self.fresno, date(2026, 7, 11))

    def test_detail(self):
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': self.forecast.sqid})
        response = self.client.get(url)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['id'] == self.forecast.sqid
        assert data['aqi_value'] == 101
        assert data['pollutant'] == 'O3'
        assert data['color'] == self.forecast.color

    def test_detail_not_found(self):
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': 'doesnotexist'})
        response = self.client.get(url)
        assert response.status_code == 404

    def test_custom_region_is_slim(self):
        sequoia = Region.objects.get(type=Region.Type.CUSTOM, name='Sequoia National Park and Forest')
        forecast = create_forecast(sequoia, date(2026, 7, 11))
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': forecast.sqid})
        region_data = self.client.get(url).json()['data']['region']
        assert region_data['type'] == 'custom'
        assert 'boundary' not in region_data


class ForecastPlaceTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()
        self.url = reverse('api:v2:forecasts:forecast-place')
        self.fresno = Region.objects.get(name='Fresno County')
        self.kern = Region.objects.get(name='Kern County')
        self.fresno_city = Region.objects.get(type=Region.Type.CITY, name='Fresno')
        self.today = localtime().date()
        self.yesterday = self.today - timedelta(days=1)
        self.tomorrow = self.today + timedelta(days=1)
        self.forecast_today = create_forecast(self.fresno, self.today)
        self.forecast_tomorrow = create_forecast(self.fresno, self.tomorrow, issued_date=self.today)
        self.forecast_yesterday = create_forecast(self.fresno, self.yesterday)

    def test_place_county_rule(self):
        response = self.client.get(self.url, {'region_type': 'county', 'region': '06019'})
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=900'
        body = response.json()['data']
        assert body['place'] == {'region': {'type': 'county', 'external_id': '06019', 'name': 'Fresno County'}}
        assert body['zone'] == {
            'id': self.fresno.sqid, 'type': 'county', 'external_id': '06019', 'name': 'Fresno County'}
        assert body['rule'] == 'county'
        assert [f['id'] for f in body['forecasts']] == [self.forecast_today.sqid, self.forecast_tomorrow.sqid]
        assert 'boundary' not in body['forecasts'][0]['region']

    def test_place_city_center_rule(self):
        response = self.client.get(self.url, {
            'region_type': 'city', 'region': self.fresno_city.external_id})
        body = response.json()['data']
        assert body['rule'] == 'center'
        assert body['zone']['id'] == self.fresno.sqid
        assert len(body['forecasts']) == 2

    def test_place_outside_valley(self):
        outside = make_region('Nowhere', Region.Type.CITY, 'nowhere', (-110, 40, -109, 41))
        response = self.client.get(self.url, {'region_type': 'city', 'region': outside.external_id})
        assert response.status_code == 200
        body = response.json()['data']
        assert body['zone'] is None
        assert body['rule'] is None
        assert body['forecasts'] == []

    def test_date_filter_overrides_default(self):
        response = self.client.get(self.url, {
            'region_type': 'county', 'region': '06019', 'forecast_date': self.yesterday.isoformat()})
        ids = [f['id'] for f in response.json()['data']['forecasts']]
        assert ids == [self.forecast_yesterday.sqid]

    def test_other_filters_are_ignored(self):
        kern_zone = Region.objects.get(name='Kern (SJV Air Basin portion)')
        create_forecast(kern_zone, self.today)
        params = {'region_type': 'county', 'region': '06019'}
        plain = self.client.get(self.url, params).json()['data']
        filtered = self.client.get(self.url, {
            **params, 'region_id': kern_zone.sqid, 'issued_date': self.yesterday.isoformat()}).json()['data']
        assert filtered == plain

    def test_monitor_target(self):
        point = self.fresno_city.boundary.geometry.point_on_surface
        monitor = CIMIS.objects.create(
            name='M', station_number='5', position=point, location=CIMIS.LOCATION.outside)
        body = self.client.get(self.url, {'monitor': str(monitor.pk)}).json()['data']
        assert body['place'] == {'monitor': str(monitor.pk)}
        assert body['rule'] == 'center'
        assert body['zone']['id'] == self.fresno.sqid
        assert len(body['forecasts']) == 2

    def test_monitor_without_position(self):
        monitor = CIMIS.objects.create(
            name='No Pos', station_number='9', position=None, location=CIMIS.LOCATION.outside)
        response = self.client.get(self.url, {'monitor': str(monitor.pk)})
        assert response.status_code == 400
        assert response.json()['error'] == 'Monitor has no location.'

    def test_errors_pass_through(self):
        assert self.client.get(self.url, {'region_type': 'land_use', 'region': '1'}).status_code == 400
        assert self.client.get(self.url, {'region_type': 'county', 'region': 'nope'}).status_code == 404
        assert self.client.get(self.url).status_code == 400

    def test_retired_region_still_answers(self):
        self.fresno_city.retired_at = timezone.now()
        self.fresno_city.save()
        response = self.client.get(self.url, {
            'region_type': 'city', 'region': self.fresno_city.external_id})
        assert response.status_code == 200
        assert response.json()['data']['zone']['id'] == self.fresno.sqid

    def test_only_the_latest_issue_per_date(self):
        # Tomorrow was also forecast yesterday (superseded); today's was
        # republished later on the same issued date (the later one wins).
        create_forecast(self.fresno, self.tomorrow, issued_date=self.yesterday)
        republished = create_forecast(self.fresno, self.today, aqi_value=55)
        republished.published_at += timedelta(hours=2)
        republished.save()
        response = self.client.get(self.url, {'region_type': 'county', 'region': '06019'})
        ids = [f['id'] for f in response.json()['data']['forecasts']]
        assert ids == [republished.sqid, self.forecast_tomorrow.sqid]

    def test_warm_request_loads_no_boundary(self):
        params = {'region_type': 'city', 'region': self.fresno_city.external_id}
        self.client.get(self.url, params)
        with CaptureQueriesContext(connection) as queries:
            assert self.client.get(self.url, params).json()['data']['rule'] == 'center'
        assert not [q['sql'] for q in queries if 'regions_boundary' in q['sql']]

    def test_route_not_shadowed(self):
        assert self.client.get('/api/2.0/forecasts/place/').status_code == 400


class ForecastMetaTests(TestCase):
    fixtures = ['regions.yaml']

    def get_data(self):
        response = self.client.get(reverse('api:v2:forecasts:forecast-meta'))
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=3600'
        return response.json()['data']

    def test_forecast_meta_scales(self):
        scales = self.get_data()['scales']
        assert set(scales) == {'aqi-forecast', 'burn-status'}

        aqi = scales['aqi-forecast']
        assert aqi['label'] == 'AQI Forecast'
        assert aqi['kind'] == 'range'
        assert len(aqi['levels']) == 6
        assert aqi['levels'][-1]['key'] == 'hazardous'
        assert aqi['levels'][-1]['max'] is None

        burn = scales['burn-status']
        assert burn['label'] == 'Burn Status'
        assert burn['kind'] == 'category'
        assert [l['key'] for l in burn['levels']] == ['discouraged', 'registered']
        assert [l['value'] for l in burn['levels']] == ['Discouraged', 'Registered']
        assert [l['label'] for l in burn['levels']] == [
            'Burning Discouraged', 'No Burning Unless Registered',
        ]
        assert [l['color'] for l in burn['levels']] == ['#ffff00', '#ff7e00']
        assert all(l['tier'] is None for l in burn['levels'])
        assert burn['source']['url'] == 'https://ww2.valleyair.org/'

    def test_forecast_meta_zones(self):
        zones = self.get_data()['zones']
        assert len(zones) == 9
        by_name = {z['name']: z['region'] for z in zones}
        fresno = Region.objects.get(name='Fresno County')
        assert by_name['Fresno'] == {
            'id': fresno.sqid,
            'type': fresno.type,
            'external_id': fresno.external_id,
            'name': 'Fresno County',
        }
        assert by_name['Sequoia National Park and Forest']['type'] == 'custom'

    def test_forecast_meta_zone_without_region(self):
        Region.objects.filter(name='Sequoia National Park and Forest').delete()
        zones = self.get_data()['zones']
        assert len(zones) == 9
        by_name = {z['name']: z['region'] for z in zones}
        assert by_name['Sequoia National Park and Forest'] is None
        assert by_name['Fresno'] is not None

    def test_meta_route_not_shadowed(self):
        response = self.client.get('/api/2.0/forecasts/meta/')
        assert 'scales' in response.json()['data']
