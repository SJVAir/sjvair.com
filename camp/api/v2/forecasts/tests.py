from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.urls import reverse

from camp.apps.forecasts.models import Forecast
from camp.apps.regions.models import Region
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

    def test_response_includes_region_boundary_geometry(self):
        response = self.client.get(self.url)
        data = response.json()['data'][0]
        assert data['region']['boundary'] is not None
        assert 'geometry' in data['region']['boundary']


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

    def test_custom_region_includes_boundary_geometry(self):
        # Kern/Tulare/Sequoia are Region(type=CUSTOM), not COUNTY -- confirm
        # RegionSerializer includes their real derived boundary the same way
        # it does for county regions (no type-based branching to regress on).
        sequoia = Region.objects.get(type=Region.Type.CUSTOM, name='Sequoia National Park and Forest')
        forecast = create_forecast(sequoia, date(2026, 7, 11))
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': forecast.sqid})
        response = self.client.get(url)
        assert response.status_code == 200
        region_data = response.json()['data']['region']
        assert region_data['type'] == 'custom'
        boundary = region_data['boundary']
        assert boundary is not None
        assert boundary['geometry']['type'] == 'MultiPolygon'
        assert len(boundary['geometry']['coordinates']) > 0


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
