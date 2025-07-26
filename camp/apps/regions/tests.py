from django.contrib.gis.geos import Polygon, MultiPolygon
from django.test import TestCase
from .models import Region


class RegionTests(TestCase):
    def test_create_region(self):
        geom = MultiPolygon(Polygon((
            (0, 0), (1, 0), (1, 1), (0, 1), (0, 0)
        )))
        region = Region.objects.create(
            name='Test Tract',
            type=Region.Type.TRACT,
            geom=geom
        )
        assert region.name == 'Test Tract'
        assert region.type == Region.Type.TRACT
