import pickle

from datetime import date

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import TestCase
from django.utils.text import slugify

from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.resolve import (
    PlaceError, PlaceNotFound, forecast_zone_for, resolve_place, zips_for,
)


def make_region(name, type, external_id, bbox, version='2020'):
    region = Region.objects.create(name=name, slug=slugify(name), type=type, external_id=external_id)
    if bbox is not None:
        region.boundary = Boundary.objects.create(
            region=region, version=version, geometry=MultiPolygon(Polygon.from_bbox(bbox), srid=4326))
        region.save(update_fields=['boundary'])
    return region


class ResolveTestCase(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, name='Fresno County')
        self.fresno_city = Region.objects.get(type=Region.Type.CITY, name='Fresno')


class OverlappingTests(TestCase):
    def setUp(self):
        # A 10x10 square "county"; ZIPs poke into it by 0.5% and 5% of their own width.
        self.county = make_region('Box County', Region.Type.COUNTY, 'box', (0, 0, 10, 10))
        self.sliver = make_region('Sliver', Region.Type.ZIPCODE, '90001', (9.995, 0, 10.995, 1))
        self.edge = make_region('Edge', Region.Type.ZIPCODE, '90002', (9.95, 0, 10.95, 1))
        self.far = make_region('Far', Region.Type.ZIPCODE, '90003', (20, 20, 21, 21))

    def test_overlapping_threshold(self):
        geometry = self.county.boundary.geometry
        found = set(Region.objects.overlapping(geometry))
        assert self.edge in found
        assert self.sliver not in found
        assert self.far not in found
        assert self.county in found


class ResolvePlaceTests(ResolveTestCase):
    def test_resolve_region(self):
        place = resolve_place({'region_type': 'county', 'region': self.fresno.external_id})
        assert place == self.fresno

    def test_resolve_region_leaves_the_boundary_unloaded(self):
        place = resolve_place({'region_type': 'county', 'region': self.fresno.external_id})
        assert 'boundary' not in place._state.fields_cache

    def test_resolve_retired_region(self):
        self.fresno_city.retire(date(2026, 1, 1))
        place = resolve_place({'region_type': 'city', 'region': self.fresno_city.external_id})
        assert place == self.fresno_city

    def test_resolve_errors(self):
        def error(params, cls=PlaceError):
            with self.assertRaises(cls) as ctx:
                resolve_place(params)
            return str(ctx.exception)

        assert error({'monitor': 'x', 'region_type': 'county'}) == 'Give either monitor or region, not both.'
        assert error({'monitor': 'x', 'region': '1'}) == 'Give either monitor or region, not both.'
        assert error({'region_type': 'county'}) == 'region_type and region go together.'
        assert error({'region': '06019'}) == 'region_type and region go together.'
        assert error({}) == 'Give a region (region_type and region) or a monitor.'
        assert error({'region_type': 'land_use', 'region': '1'}) == "Land-use regions can't be looked up by code yet."
        assert error({'region_type': 'county', 'region': 'nope'}, PlaceNotFound) == 'No such region: county nope.'
        assert error({'monitor': 'nope'}, PlaceNotFound) == 'No such monitor: nope.'
        assert issubclass(PlaceNotFound, PlaceError)

    def test_resolve_monitor_without_position(self):
        monitor = CIMIS.objects.create(name='No Pos', station_number='9', position=None, location=CIMIS.LOCATION.outside)
        with self.assertRaises(PlaceError) as ctx:
            resolve_place({'monitor': str(monitor.pk)})
        assert str(ctx.exception) == 'Monitor has no location.'
        assert not isinstance(ctx.exception, PlaceNotFound)

    def test_resolve_monitor(self):
        monitor = CIMIS.objects.create(
            name='Pos', station_number='8', position=Point(-119.78, 36.74, srid=4326), location=CIMIS.LOCATION.outside)
        assert resolve_place({'monitor': str(monitor.pk)}).pk == monitor.pk


class ZipsForTests(ResolveTestCase):
    def test_zips_for_zip_is_itself(self):
        zipcode = Region.objects.get(type=Region.Type.ZIPCODE, external_id='93728')
        assert zips_for(zipcode) == [zipcode]

    def test_zips_for_county(self):
        county = make_region('Box County', Region.Type.COUNTY, 'box', (0, 0, 10, 10))
        inside = make_region('Inside', Region.Type.ZIPCODE, '90010', (1, 1, 2, 2))
        make_region('Outside', Region.Type.ZIPCODE, '90011', (20, 20, 21, 21))
        retired = make_region('Retired', Region.Type.ZIPCODE, '90012', (3, 3, 4, 4))
        retired.retire(date(2026, 1, 1))
        assert zips_for(county) == [inside]

    def test_zips_for_no_boundary_is_empty(self):
        county = make_region('Bare County', Region.Type.COUNTY, 'bare', None)
        assert zips_for(county) == []

    def test_zips_for_monitor(self):
        zipcode = make_region('Mon Zip', Region.Type.ZIPCODE, '90020', (-100, 30, -99, 31))
        inside = CIMIS.objects.create(
            name='In', station_number='7', position=Point(-99.5, 30.5, srid=4326), location=CIMIS.LOCATION.outside)
        outside = CIMIS.objects.create(
            name='Out', station_number='6', position=Point(-90, 30.5, srid=4326), location=CIMIS.LOCATION.outside)
        assert zips_for(inside) == [zipcode]
        assert zips_for(outside) == []

    def test_zips_for_cached(self):
        county = make_region('Box County', Region.Type.COUNTY, 'box', (0, 0, 10, 10))
        inside = make_region('Inside', Region.Type.ZIPCODE, '90010', (1, 1, 2, 2))
        county = Region.objects.select_related('boundary').get(pk=county.pk)
        assert zips_for(county) == [inside]
        with self.assertNumQueries(0):
            assert zips_for(county) == [inside]


class ForecastZoneTests(ResolveTestCase):
    def test_zone_rules(self):
        assert forecast_zone_for(self.fresno) == (self.fresno, 'county')
        assert forecast_zone_for(self.fresno_city) == (self.fresno, 'center')

        outside = make_region('Nowhere', Region.Type.CITY, 'nowhere', (-110, 40, -109, 41))
        assert forecast_zone_for(outside) == (None, None)

        tulare_zone = Region.objects.get(type=Region.Type.CUSTOM, name='Tulare (SJV Valley portion)')
        assert forecast_zone_for(tulare_zone) == (tulare_zone, 'zone')

    def test_county_maps_to_custom_zone(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, name='Kern County')
        tulare = Region.objects.get(type=Region.Type.COUNTY, name='Tulare County')
        kern_zone = Region.objects.get(name='Kern (SJV Air Basin portion)')
        tulare_zone = Region.objects.get(name='Tulare (SJV Valley portion)')
        assert forecast_zone_for(kern) == (kern_zone, 'county')
        assert forecast_zone_for(tulare) == (tulare_zone, 'county')

    def test_overlap_rule(self):
        # A box hanging off the west edge: its center is outside every zone,
        # but it overlaps some; the zone sharing the most area wins.
        west = self.fresno.boundary.geometry.extent[0]
        south, north = 36.0, 37.5
        straddler = make_region('Straddle', Region.Type.CUSTOM, 'straddle', (west - 3, south, west + 0.3, north))
        zone, rule = forecast_zone_for(straddler)
        assert rule == 'overlap'

        geometry = straddler.boundary.geometry
        zones = Region.objects.filter(type=Region.Type.COUNTY).exclude(name__in=['Kern County', 'Tulare County'])
        expected = max(zones, key=lambda r: r.boundary.geometry.intersection(geometry).area)
        assert zone == expected

    def test_monitor_center(self):
        point = self.fresno_city.boundary.geometry.point_on_surface
        monitor = CIMIS.objects.create(name='M', station_number='5', position=point, location=CIMIS.LOCATION.outside)
        assert forecast_zone_for(monitor) == (self.fresno, 'center')

    def test_forecast_zone_cached(self):
        forecast_zone_for(self.fresno_city)
        with self.assertNumQueries(0):
            assert forecast_zone_for(self.fresno_city) == (self.fresno, 'center')


class CachedPlacesCarryNoGeometryTests(ResolveTestCase):
    def assert_no_geometry(self, region):
        assert 'boundary' not in region._state.fields_cache
        assert len(pickle.dumps(region)) < 5000

    def test_cached_zips_and_zones_carry_no_geometry(self):
        county = make_region('Box County', Region.Type.COUNTY, 'box', (0, 0, 10, 10))
        make_region('Inside', Region.Type.ZIPCODE, '90010', (1, 1, 2, 2))
        county = Region.objects.select_related('boundary').get(pk=county.pk)
        for zip_region in zips_for(county):
            self.assert_no_geometry(zip_region)

        # The caller's own region (boundary loaded) must not leak into the cache.
        tulare_zone = Region.objects.select_related('boundary').get(name='Tulare (SJV Valley portion)')
        zone, rule = forecast_zone_for(tulare_zone)
        assert rule == 'zone'
        self.assert_no_geometry(zone)
        for place in (self.fresno, self.fresno_city):
            zone, _ = forecast_zone_for(place)
            self.assert_no_geometry(zone)
