from django.contrib.gis.geos import Polygon, MultiPolygon
from django.test import TestCase

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region, Boundary


class RegionTests(TestCase):
    fixtures = ['regions_split', 'purple-air']

    def test_create_region(self):
        geom = MultiPolygon(Polygon((
            (0, 0), (1, 0), (1, 1), (0, 1), (0, 0)
        )))
        region = Region.objects.create(
            name='Test Tract',
            type=Region.Type.TRACT,
        )
        boundary = Boundary.objects.create(
            region=region,
            version='test',
            geometry=geom,
        )
        region.boundary = boundary
        region.save()

        assert region.name == 'Test Tract'
        assert region.type == Region.Type.TRACT
        assert region.boundary.geometry.equals(geom)

    def test_region_monitors(self):
        monitor = PurpleAir.objects.get(purple_id=8892)
        fresno = Region.objects.get(name='Fresno County')
        kern = Region.objects.get(name='Kern County')

        assert fresno.pk in monitor.regions.values_list('pk', flat=True)
        assert monitor.pk in fresno.monitors.values_list('pk', flat=True)

        assert kern.pk not in monitor.regions.values_list('pk', flat=True)
        assert monitor.pk not in kern.monitors.values_list('pk', flat=True)

    def test_intersects_point(self):
        monitor = PurpleAir.objects.get(purple_id=8892)
        result = Region.objects.intersects(monitor.position)

        # Should intersect City of Fresno and Fresno Unified
        names = set(result.values_list('name', flat=True))
        assert 'Fresno' in names
        assert 'Fresno Unified' in names
        assert '93728' in names

    def test_intersects_sjv_counties(self):
        # Rough bounding box covering the Central Valley floor
        valley_box = Polygon.from_bbox((-122, 34.5, -118, 38))
        counties = Region.objects.filter(type=Region.Type.COUNTY)
        expected = set(counties.values_list('name', flat=True))
        result = counties.intersects(valley_box)

        assert result.count() == 8
        assert set(result.values_list('name', flat=True)) == expected

    def test_combined_geometry_union(self):
        counties = Region.objects.filter(type=Region.Type.COUNTY)
        combined = counties.combined_geometry()

        assert isinstance(combined, (Polygon, MultiPolygon))
        assert combined.num_points > 0

        # Quick reality check: Fresno centroid should fall inside
        fresno = Region.objects.get(name='Fresno County', type=Region.Type.COUNTY)
        assert combined.contains(fresno.boundary.geometry.centroid)
