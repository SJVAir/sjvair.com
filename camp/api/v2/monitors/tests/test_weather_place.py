from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve
from django.utils import timezone
from django.utils.text import slugify

from camp.api.v2.monitors.places import WeatherStationsPlace
from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.regions.models import Boundary, Region


def make_region(name, type, external_id, bbox, version='2020'):
    region = Region.objects.create(name=name, slug=slugify(name), type=type, external_id=external_id)
    region.boundary = Boundary.objects.create(
        region=region, version=version, geometry=MultiPolygon(Polygon.from_bbox(bbox), srid=4326))
    region.save(update_fields=['boundary'])
    return region


def make_station(name, number, lon, lat, active=True, latest=None, **kw):
    position = None if lon is None else Point(lon, lat, srid=4326)
    station = CIMIS.objects.create(
        name=name, station_number=number, position=position, location=CIMIS.LOCATION.outside, **kw)
    if active:
        station.create_entry(
            entry_models.Temperature, timestamp=latest or timezone.now(), value=60, sensor='')
    return station


class WeatherStationsPlaceTests(TestCase):
    url = '/api/2.0/monitors/weather/place/'

    def setUp(self):
        cache.clear()
        self.region = make_region('Box County', Region.Type.COUNTY, 'box', (-119.9, 36.6, -119.6, 36.9))

    def test_region_lists_stations(self):
        a = make_station('A', '1', -119.75, 36.75)
        c = make_station('C', '3', -119.50, 36.75)
        response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=900'
        body = response.json()['data']
        assert body['place'] == {'region': {'type': 'county', 'external_id': 'box', 'name': 'Box County'}}
        assert [s['id'] for s in body['stations']] == [str(a.pk), str(c.pk)]
        assert body['stations'][0]['type'] == 'cimis'
        assert body['stations'][0]['distance'] == 0.0 and body['stations'][0]['inside'] is True
        assert body['stations'][1]['inside'] is False

    def test_monitor_place(self):
        me = make_station('Me', '12', -119.75, 36.75)
        body = self.client.get(self.url, {'monitor': str(me.pk)}).json()['data']
        assert body['place'] == {'monitor': str(me.pk)}
        assert body['stations'][0]['id'] == str(me.pk)

    def test_no_stations_is_empty_200(self):
        response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
        assert response.status_code == 200 and response.json()['data']['stations'] == []

    def test_retired_region_answers(self):
        self.region.retired_at = timezone.now()
        self.region.save()
        make_station('A', '1', -119.75, 36.75)
        response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
        assert response.status_code == 200 and len(response.json()['data']['stations']) == 1

    def test_errors(self):
        assert self.client.get(self.url).status_code == 400
        assert self.client.get(self.url, {'region_type': 'land_use', 'region': '1'}).status_code == 400
        missing = self.client.get(self.url, {'region_type': 'county', 'region': 'nope'})
        assert missing.status_code == 404 and missing['Cache-Control'] == 'no-cache'
        hidden = make_station('H', '20', -119.75, 36.75, is_hidden=True)
        assert self.client.get(self.url, {'monitor': str(hidden.pk)}).status_code == 404

    def test_url_does_not_shadow_monitor_routes(self):
        assert resolve('/api/2.0/monitors/weather/place/').func.view_class is WeatherStationsPlace
        assert resolve('/api/2.0/monitors/pm25/closest/').url_name == 'monitor-closest'
        assert resolve('/api/2.0/monitors/weather/').url_name == 'monitor-detail'
