from unittest.mock import patch

import numpy as np
import pytest
from django.contrib.gis.geos import Polygon, MultiPolygon
from django.test import TestCase
from shapely.geometry import Polygon as ShapelyPolygon

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region, Boundary
from camp.apps.regions.management.commands.import_mtrs import build_mtrs
from camp.apps.regions.forecast_zones import (
    MIN_ACCEPTABLE_IOU,
    derive_forecast_zones,
    fit_affine,
    iou,
    load_svg_shapes,
    parse_svg_path,
    region_boundary_shape,
    transform_polygon,
)


class RegionTests(TestCase):
    fixtures = ['regions', 'purple-air']

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
        monitor = PurpleAir.objects.get(sensor_id=8892)
        fresno = Region.objects.get(name='Fresno County')
        kern = Region.objects.get(name='Kern County')

        assert fresno.pk in monitor.regions.values_list('pk', flat=True)
        assert monitor.pk in fresno.monitors.values_list('pk', flat=True)

        assert kern.pk not in monitor.regions.values_list('pk', flat=True)
        assert monitor.pk not in kern.monitors.values_list('pk', flat=True)

    def test_intersects_point(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
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


class BuildMtrsTests(TestCase):
    def test_single_digit_section_is_zero_padded(self):
        assert build_mtrs('MD', 'T13S', 'R14E', 8) == 'MD-T13S-R14E-08'

    def test_section_one_is_zero_padded(self):
        assert build_mtrs('MD', 'T13S', 'R14E', 1) == 'MD-T13S-R14E-01'

    def test_two_digit_section_is_unchanged(self):
        assert build_mtrs('MD', 'T13S', 'R14E', 36) == 'MD-T13S-R14E-36'

    def test_different_meridian(self):
        assert build_mtrs('HM', 'T01N', 'R01E', 5) == 'HM-T01N-R01E-05'

    def test_mtrs_region_type_exists(self):
        assert Region.Type.MTRS == 'mtrs'


SVG_PATH = 'datafiles/sjvapcd-forecast-areas.svg'


class ParseSvgPathTests(TestCase):
    def test_parses_move_and_line_commands(self):
        points = parse_svg_path('M 0 0 L 10 0 10 10 0 10 Z')
        assert points == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

    def test_handles_floats(self):
        points = parse_svg_path('M 1.5 2.25 L 3.75 4.125 Z')
        assert points == [(1.5, 2.25), (3.75, 4.125)]


class FitAffineTests(TestCase):
    def test_recovers_known_translation_and_scale(self):
        # svg (x, y) -> real (lon, lat) via lon = 2x + 100, lat = -3y + 50
        gcp_svg = [(0, 0), (10, 0), (0, 10), (5, 5)]
        gcp_real = [(2 * x + 100, -3 * y + 50) for x, y in gcp_svg]

        lon_coef, lat_coef = fit_affine(gcp_svg, gcp_real)

        assert lon_coef == pytest.approx([2, 0, 100])
        assert lat_coef == pytest.approx([0, -3, 50])


class TransformPolygonTests(TestCase):
    def test_applies_affine_transform_to_every_vertex(self):
        square = ShapelyPolygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        lon_coef = np.array([2, 0, 100])
        lat_coef = np.array([0, -3, 50])

        transformed = transform_polygon(square, lon_coef, lat_coef)

        assert list(transformed.exterior.coords)[:-1] == pytest.approx(
            [(100, 50), (120, 50), (120, 20), (100, 20)]
        )


class IouTests(TestCase):
    def test_identical_polygons_have_iou_of_one(self):
        square = ShapelyPolygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        assert iou(square, square) == pytest.approx(1.0)

    def test_non_overlapping_polygons_have_iou_of_zero(self):
        a = ShapelyPolygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        b = ShapelyPolygon([(5, 5), (6, 5), (6, 6), (5, 6)])
        assert iou(a, b) == 0.0

    def test_half_overlapping_squares(self):
        a = ShapelyPolygon([(0, 0), (2, 0), (2, 2), (0, 2)])  # area 4
        b = ShapelyPolygon([(1, 0), (3, 0), (3, 2), (1, 2)])  # overlap area 2 (x in [1,2])
        # intersection area = 1*2 = 2, union = 4+4-2 = 6, iou = 2/6 = 1/3
        assert iou(a, b) == pytest.approx(1 / 3)


class LoadSvgShapesTests(TestCase):
    def test_loads_all_nine_named_zones(self):
        shapes = load_svg_shapes(SVG_PATH)
        assert set(shapes.keys()) == {
            'san-joaquin', 'stanislaus', 'merced', 'madera', 'fresno', 'kings',
            'tulare', 'kern-(sjv air basin portion)', 'sequoia-national park and forest',
        }
        for name, polygon in shapes.items():
            assert polygon.is_valid, name
            assert polygon.area > 0, name


class DeriveForecastZonesTests(TestCase):
    fixtures = ['regions.yaml']

    def test_ground_control_fit_validates_well(self):
        result = derive_forecast_zones(SVG_PATH)
        for shape_id, score in result['gcp_iou'].items():
            assert score >= MIN_ACCEPTABLE_IOU, f'{shape_id}: {score}'

    def test_derived_zones_are_valid_and_nonempty(self):
        result = derive_forecast_zones(SVG_PATH)
        for key in ('kern_airbasin', 'tulare_valley', 'sequoia'):
            geom = result[key]
            assert geom.is_valid, key
            assert geom.area > 0, key

    def test_tulare_and_sequoia_tile_real_tulare_with_no_gap_or_overlap(self):
        result = derive_forecast_zones(SVG_PATH)
        real_tulare = region_boundary_shape('Tulare County')
        combined = result['tulare_valley'].union(result['sequoia'])
        assert iou(combined, real_tulare) > 0.9999

    def test_derived_zones_match_imported_fixture_regions(self):
        # fixtures/regions.yaml's custom regions were generated by this exact
        # derivation against the same SVG -- re-deriving should reproduce
        # (near-)identical geometry. Not a perfect 1.0: the fixture geometry
        # went through a WKT/GeoJSON round-trip on its way into and out of
        # the database, which loses a little coordinate precision. A future
        # edit that breaks the derivation math would show up here as IoU
        # dropping well below this threshold, not by a fraction of a percent.
        result = derive_forecast_zones(SVG_PATH)
        cases = [
            ('kern_airbasin', 'Kern (SJV Air Basin portion)'),
            ('tulare_valley', 'Tulare (SJV Valley portion)'),
            ('sequoia', 'Sequoia National Park and Forest'),
        ]
        for key, region_name in cases:
            fixture_geom = region_boundary_shape(region_name, region_type=Region.Type.CUSTOM)
            assert iou(result[key], fixture_geom) > 0.99, region_name

    def test_raises_when_ground_control_fit_is_untrustworthy(self):
        # Deliberately mismatched svg-shape-to-county pairings should produce
        # a garbage affine fit that fails the IoU validation gate.
        scrambled = {
            'san-joaquin': 'Kern County',
            'stanislaus': 'Tulare County',
            'merced': 'Fresno County',
            'madera': 'Kings County',
            'fresno': 'Madera County',
            'kings': 'Merced County',
        }
        with patch('camp.apps.regions.forecast_zones.GROUND_CONTROL_COUNTIES', scrambled):
            with pytest.raises(RuntimeError, match='IoU'):
                derive_forecast_zones(SVG_PATH)
