from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase

from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.nearby import counterpart


def square(west, south, size=0.1):
    return MultiPolygon(Polygon.from_bbox((west, south, west + size, south + size)), srid=4326)


def make(name, kind, geometry):
    region = Region.objects.create(name=name, slug=f'{name.lower()}-{kind}', type=kind, external_id=f'{name}-{kind}')
    region.boundary = Boundary.objects.create(region=region, version='t', geometry=geometry)
    region.save()
    return region


class CounterpartTests(TestCase):
    """A city or CDP and the urban area of the same name: each points to the other."""

    def test_city_and_urban_area_point_to_each_other(self):
        city = make('Selma', Region.Type.CITY, square(-119.6, 36.5))
        urban = make('Selma', Region.Type.URBAN_AREA, square(-119.62, 36.48, 0.15))
        assert counterpart(city) == urban
        assert counterpart(urban) == city

    def test_a_cdp_finds_its_urban_area(self):
        cdp = make('Caruthers', Region.Type.CDP, square(-119.8, 36.5))
        urban = make('Caruthers', Region.Type.URBAN_AREA, square(-119.8, 36.5))
        assert counterpart(cdp) == urban and counterpart(urban) == cdp

    def test_the_same_name_elsewhere_is_not_a_match(self):
        city = make('Delano', Region.Type.CITY, square(-119.2, 35.7))
        make('Delano', Region.Type.URBAN_AREA, square(-118.0, 34.0))
        assert counterpart(city) is None

    def test_only_community_layers_have_one(self):
        county = make('Fresno', Region.Type.COUNTY, square(-120.0, 36.0, 1))
        make('Fresno', Region.Type.CITY, square(-119.8, 36.7))
        assert counterpart(county) is None

    def test_no_match(self):
        assert counterpart(make('Biola', Region.Type.CDP, square(-120.0, 36.8))) is None
