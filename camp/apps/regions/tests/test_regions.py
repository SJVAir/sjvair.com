from unittest.mock import patch

import numpy as np
import pytest
from django.contrib.gis.geos import Point, Polygon, MultiPolygon
from django.test import RequestFactory, TestCase
from django.urls import reverse
from shapely.geometry import Polygon as ShapelyPolygon

from camp.apps.accounts.models import User
from camp.apps.ces.models import CES4, CES5
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.counties import COUNTY_KEYS, COUNTY_NAMES, county_name
from camp.apps.regions.models import Region, Boundary
from camp.apps.regions.panels import MonitorsPanel, TractPanel, panels_for
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


class ImportOrUpdateTests(TestCase):
    def make_geometry(self):
        return MultiPolygon(Polygon((
            (0, 0), (1, 0), (1, 1), (0, 1), (0, 0)
        )))

    def test_reimport_carries_over_population(self):
        # import_population writes metadata['population'] separately from
        # the region imports (import_counties etc.), which call
        # import_or_update with their own metadata dict that knows nothing
        # about population. A re-import must not drop it.
        geometry = self.make_geometry()
        region, _ = Region.objects.import_or_update(
            name='Test County', slug='test-county', type=Region.Type.COUNTY,
            external_id='06999', geometry=geometry, version='v1',
            metadata={'fips': '06999'},
        )
        region.metadata['population'] = 12345
        region.save(update_fields=['metadata'])

        region, _ = Region.objects.import_or_update(
            name='Test County', slug='test-county', type=Region.Type.COUNTY,
            external_id='06999', geometry=geometry, version='v1',
            metadata={'fips': '06999'},
        )
        assert region.metadata['population'] == 12345
        assert region.metadata['fips'] == '06999'

    def test_reimport_with_its_own_population_wins(self):
        geometry = self.make_geometry()
        region, _ = Region.objects.import_or_update(
            name='Test County', slug='test-county', type=Region.Type.COUNTY,
            external_id='06999', geometry=geometry, version='v1',
            metadata={'population': 1},
        )
        region, _ = Region.objects.import_or_update(
            name='Test County', slug='test-county', type=Region.Type.COUNTY,
            external_id='06999', geometry=geometry, version='v1',
            metadata={'population': 2},
        )
        assert region.metadata['population'] == 2

    def test_first_import_without_population_has_none(self):
        geometry = self.make_geometry()
        region, _ = Region.objects.import_or_update(
            name='Test County', slug='test-county', type=Region.Type.COUNTY,
            external_id='06999', geometry=geometry, version='v1',
            metadata={'fips': '06999'},
        )
        assert 'population' not in region.metadata


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


class RegionPanelTests(TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        self.user = User.objects.create_superuser(
            email='admin@example.com', password='password', phone='+15595551234', full_name='Admin',
        )
        self.client.force_login(self.user)
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.tract = Region.objects.get(external_id='06019000101', type=Region.Type.TRACT)
        self.district = Region.objects.get(type=Region.Type.SCHOOL_DISTRICT)
        self.monitor = PurpleAir.objects.create(name='Downtown', sensor_id=1, position=Point(-119.79, 36.74), location='outside')

    def test_panels_are_chosen_by_region_type(self):
        # Other apps register their own panels, so assert the type-specific
        # ones land on the right region rather than pinning the exact list.
        tract = [type(p) for p in panels_for(self.tract, self.request)]
        district = [type(p) for p in panels_for(self.district, self.request)]
        assert TractPanel in tract and MonitorsPanel not in tract
        assert MonitorsPanel in district and TractPanel not in district

    def test_region_without_boundary_gets_no_panels(self):
        region = Region.objects.create(name='Nowhere', slug='nowhere', type=Region.Type.TRACT, external_id='0')
        assert panels_for(region, self.request) == []

    def test_tract_panel_lists_ces_records_newest_first(self):
        context = TractPanel(self.tract, self.request).get_context()
        labels = [record['label'] for record in context['records']]
        assert labels[0] == 'CalEnviroScreen 5.0 (2020 tracts)'
        assert 'CalEnviroScreen 4.0 (2010 tracts)' in labels
        fields = dict(context['records'][0]['fields'])
        assert fields['Total Population'] == 4650
        assert fields['SB535 DAC'] is True
        assert 'DAC Category' in fields
        assert fields['CES Score Percentile'] == 89.2
        # The details block is the full dump; the headline/comparison view is indicators().
        assert len(context['records'][0]['fields']) > len(TractPanel.HEADLINE)

    def test_long_monitor_lists_are_collapsed(self):
        square = Region.objects.create(name='Square', slug='square', type=Region.Type.CUSTOM, external_id='sq')
        square.boundary = Boundary.objects.create(region=square, version='latest',
            geometry=MultiPolygon(Polygon.from_bbox((-119.8, 36.7, -119.7, 36.8))))
        square.save()
        for i in range(2, 13):
            PurpleAir.objects.create(name=f'PA {i}', sensor_id=i, position=Point(-119.75, 36.75), location='outside')
        content = self.client.get(reverse('admin:regions_region_change', args=[square.pk])).content.decode()
        assert 'Show all 12 monitors' in content
        assert '<details' in content

    def test_monitors_panel_lists_monitors_inside(self):
        context = MonitorsPanel(self.district, self.request).get_context()
        names = {row['name'] for row in context['rows']}
        assert context['counts']['total'] == len(context['rows'])
        # The fixture district is Fresno Unified; whether Downtown is inside depends on
        # its real boundary, so only assert the shape here and the containment on a
        # region we control.
        square = Region.objects.create(name='Square', slug='square', type=Region.Type.CUSTOM, external_id='sq')
        square.boundary = Boundary.objects.create(region=square, version='latest',
            geometry=MultiPolygon(Polygon.from_bbox((-119.8, 36.7, -119.7, 36.8))))
        square.save()
        context = MonitorsPanel(square, self.request).get_context()
        assert [row['name'] for row in context['rows']] == ['Downtown']
        assert context['rows'][0]['status'] == 'Inactive'
        assert context['counts'] == {'total': 1, 'active': 0, 'inactive': 1, 'hidden': 0, 'sjvair': 0}
        assert names is not None

    def test_panels_are_ordered(self):
        from camp.apps.regions.panels import PANELS, Panel, panels_for

        class Late(Panel):
            types = (Region.Type.TRACT,)
            order = 200
            title = 'Late'

        class Early(Panel):
            types = (Region.Type.TRACT,)
            order = 1
            title = 'Early'

        PANELS.extend([Late, Early])
        try:
            titles = [p.title for p in panels_for(self.tract, self.request)]
            assert titles[0] == 'Early' and titles[-1] == 'Late'
        finally:
            PANELS.remove(Late)
            PANELS.remove(Early)

    def test_context_is_computed_once_and_feeds_tiles(self):
        panel = MonitorsPanel(self.district, self.request)
        calls = []
        original = panel.get_context

        def counting():
            calls.append(1)
            return original()
        panel.get_context = counting
        panel.render()
        panel.tiles()
        assert len(calls) == 1
        assert panel.tiles() == [('Active monitors', f"{panel.context['counts']['active']} / {panel.context['counts']['total']}")]

    def test_change_page_has_tile_row_and_collapsed_fields(self):
        content = self.client.get(reverse('admin:regions_region_change', args=[self.district.pk])).content.decode()
        assert 'class="region-tiles"' in content
        assert 'Active monitors' in content
        assert 'class="module aligned collapse' in content  # the Region fieldset is collapsed
        assert content.index('class="region-tiles"') < content.index('class="module aligned region-panel"')

    def test_param_links_keep_other_params(self):
        request = RequestFactory().get('/', {'range': '90d', 'pollutant': 'o3'})
        request.user = self.user
        panel = MonitorsPanel(self.district, request)
        links = {label: (url, active) for label, url, active in panel.param_links('range', [('30d', '30 days'), ('90d', '90 days')])}
        assert links['90 days'][1] is True
        assert 'pollutant=o3' in links['30 days'][0]
        assert 'range=30d' in links['30 days'][0]

    def test_admin_change_page_renders_panels(self):
        response = self.client.get(reverse('admin:regions_region_change', args=[self.tract.pk]))
        assert response.status_code == 200
        content = response.content.decode()
        assert '<h2>CalEnviroScreen</h2>' in content
        assert 'CalEnviroScreen 5.0 (2020 tracts)' in content
        # Non-numeric and null cells must survive rendering: floatformat blanks
        # both, so the rounding is done in display() instead.
        assert '<td>Yes</td>' in content  # SB535 DAC
        assert 'Top 25% CES overall score' in content  # DAC Category choice label
        # Cleanup Sites is null in both fixture records for this tract.
        assert '<tr><th>Cleanup Sites</th><td class="num">—</td><td class="num">—</td><td class="num">—</td><td class="num">—</td></tr>' in content

    def test_tract_indicator_grid(self):
        context = TractPanel(self.tract, self.request).context
        indicators = context['indicators']
        assert indicators['versions'] == ['CES5', 'CES4']
        headline = {label: values for label, *values in indicators['headline']}
        assert headline['Total Population'][0] == 4650
        assert headline['CES Score Percentile'][0] == 89.2
        assert headline['SB535 DAC'] == ['Yes', 'Yes']
        groups = {group['label']: group for group in indicators['groups']}
        assert set(groups) == {'Pollution burden', 'Population characteristics'}
        pollution = groups['Pollution burden']
        assert pollution['score'][0] == 'Pollution Burden Score'
        labels = [row[0] for row in pollution['rows']]
        assert 'PM2.5' in labels and 'Ozone' in labels
        assert all(len(row) == 5 for row in pollution['rows'])
        # Exact cells: value then percentile, CES5 before CES4.
        ces5 = CES5.objects.get(boundary__region=self.tract, boundary__version='2020')
        ces4 = CES4.objects.get(boundary__region=self.tract, boundary__version='2020')
        rows = {row[0]: row for row in pollution['rows']}
        assert rows['PM2.5'] == ('PM2.5', ces5.pol_pm, ces5.pol_pm_p, ces4.pol_pm, ces4.pol_pm_p)
        # CES5-only indicator: no CES4 field to read, so both CES4 cells are None.
        assert rows['Small Air Toxic Sites'] == ('Small Air Toxic Sites', ces5.pol_small_ats, ces5.pol_small_ats_p, None, None)
        char_rows = {row[0]: row for row in groups['Population characteristics']['rows']}
        assert char_rows['Diabetes Prevalence'] == ('Diabetes Prevalence', ces5.char_diabetes, ces5.char_diabetes_p, None, None)
        tiles = dict(TractPanel(self.tract, self.request).tiles())
        assert tiles == {'CES percentile': '89.2', 'SB535 DAC': 'Yes'}

    def test_tract_grid_blanks_missing_sentinels_and_rounds_tile(self):
        ces4 = CES4.objects.get(boundary__region=self.tract, boundary__version='2020')
        ces4.char_lbw = -999.0
        ces4.save()
        ces5 = CES5.objects.get(boundary__region=self.tract, boundary__version='2020')
        ces5.ci_score_p = 89.0955
        ces5.save()
        panel = TractPanel(self.tract, self.request)
        groups = {group['label']: group for group in panel.context['indicators']['groups']}
        rows = {row[0]: row for row in groups['Population characteristics']['rows']}
        assert rows['Low Birth Weight'][3] is None
        assert dict(panel.tiles())['CES percentile'] == '89.1'


class PlaceNameOverrideTests(TestCase):
    def test_known_geoid_is_renamed(self):
        from camp.apps.regions.management.commands.import_cities import NAME_OVERRIDES, place_name
        assert place_name('0673794', 'Squaw Valley') == 'Yokuts Valley'
        assert '0673794' in NAME_OVERRIDES

    def test_other_places_keep_their_source_name(self):
        from camp.apps.regions.management.commands.import_cities import place_name
        assert place_name('0627000', 'Fresno') == 'Fresno'
        assert place_name(627000, 'Fresno') == 'Fresno'  # numeric GEOIDs are coerced


class CountyNameTests(TestCase):
    fixtures = ['regions.yaml']

    def test_point_inside_a_county(self):
        assert county_name(Point(-119.7871, 36.7378, srid=4326)) == 'Fresno'

    def test_point_outside_the_valley(self):
        assert county_name(Point(-118.2437, 34.0522, srid=4326)) == ''  # Los Angeles
        assert county_name(Point(-118.2437, 34.0522, srid=4326), default='n/a') == 'n/a'

    def test_no_point(self):
        assert county_name(None) == ''

    def test_name_lists(self):
        assert COUNTY_NAMES == ['Fresno', 'Kern', 'Kings', 'Madera', 'Merced', 'San Joaquin', 'Stanislaus', 'Tulare']
        assert COUNTY_KEYS['san_joaquin'] == 'San Joaquin'


class CountyNameWithoutRegionsTests(TestCase):
    def test_warns_when_no_county_regions_are_loaded(self):
        with self.assertLogs('camp.apps.regions.counties', level='WARNING') as logs:
            assert county_name(Point(-119.7871, 36.7378, srid=4326)) == ''
        assert 'import_counties' in logs.output[0]
