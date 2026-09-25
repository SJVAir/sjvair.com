from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import maps
from camp.apps.regions.models import Region


class CountyGeometryTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_returns_geojson_per_county(self):
        data = maps.county_geometries()
        assert set(data) == {9001, 9002}
        assert data[9001].startswith('{')
        assert 'MultiPolygon' in data[9001]

    def test_cached(self):
        maps.county_geometries()
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001, 9002}
        cache.clear()
        assert set(maps.county_geometries()) == {9001}

    def test_skips_counties_without_boundary(self):
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001}


class QuantileClassTests(TestCase):
    def test_skewed_values_use_every_class(self):
        # One county dwarfs the rest; share-of-max would put 7 of 8 in the
        # lightest bin. Quantiles spread them across every class -- with
        # eight steps and eight counties, one each.
        values = {1: 1_000_000, 2: 5000, 3: 4000, 4: 3000, 5: 2000, 6: 1000, 7: 500, 8: 100}
        classes = maps.quantile_classes(values)
        assert len(classes.breaks) == maps.CLASSES == 8
        assert classes.index_for(1_000_000) == 7
        assert classes.index_for(100) == 0
        assert {classes.index_for(v) for v in values.values()} == set(range(8))

    def test_ties_share_a_class(self):
        values = {1: 10, 2: 10, 3: 10, 4: 50, 5: 50, 6: 900}
        classes = maps.quantile_classes(values)
        assert classes.index_for(10) == classes.index_for(10)
        assert len({classes.index_for(v) for v in values.values()}) == 3
        assert classes.index_for(900) == len(classes.breaks) - 1

    def test_fewer_values_than_classes(self):
        classes = maps.quantile_classes({1: 150.0, 2: 30.0})
        assert len(classes.breaks) == 2
        assert classes.index_for(30.0) == 0
        assert classes.index_for(150.0) == 1
        assert classes.colors[-1] == maps.RAMP[-1]

    def test_zero_and_none_are_no_data(self):
        classes = maps.quantile_classes({1: 0, 2: None, 3: 40})
        assert len(classes.breaks) == 1
        assert classes.color_for(0) == maps.NO_DATA
        assert classes.color_for(None) == maps.NO_DATA
        assert classes.color_for(40) == maps.RAMP[-1]

    def test_empty(self):
        classes = maps.quantile_classes({})
        assert classes.breaks == []
        assert classes.legend() == []

    def test_legend_ranges_cover_members(self):
        values = {1: 100, 2: 250, 3: 400, 4: 4000, 5: 90_000}
        classes = maps.quantile_classes(values)
        legend = classes.legend()
        assert len(legend) == len(classes.breaks)
        assert legend[0]['low'] == 100
        assert legend[-1]['high'] == 90_000
        assert legend[-1]['color'] == maps.RAMP[-1]
        for row in legend:
            assert row['low'] <= row['high']


class SampleRampTests(TestCase):
    def test_interpolates_between_stops(self):
        ramp = ['#000000', '#ffffff']
        assert maps.sample_ramp(ramp, 2) == ['#000000', '#ffffff']
        assert maps.sample_ramp(ramp, 3) == ['#000000', '#808080', '#ffffff']

    def test_more_classes_than_stops_never_repeats(self):
        # Selecting the nearest stop (what this replaces) would hand back
        # duplicates here, so two classes would share a fill.
        colors = maps.sample_ramp(['#000000', '#ffffff'], 5)
        assert len(set(colors)) == 5

    def test_single_class_takes_the_darkest(self):
        assert maps.sample_ramp(maps.RAMP, 1) == [maps.RAMP[-1]]

    def test_quantile_classes_still_end_on_the_darkest(self):
        classes = maps.quantile_classes({i: i * 10 for i in range(1, 9)})
        assert classes.colors[-1] == maps.RAMP[-1]
        assert classes.colors[0] == maps.RAMP[0]


class CountyMapTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.rows = [
            {'county_id': 9001, 'county_name': 'Fresno County', 'county_slug': 'fresno', 'lbs': 150.0, 'acres': 15, 'applications': 2},
        ]

    def test_counties_link_to_their_pages(self):
        html = maps.county_map(self.rows, query='year=2020')
        fresno = Region.objects.get(pk=9001)
        assert f'"url": "/tools/pesticides/region/{fresno.sqid}/{fresno.slug}/?year=2020"' in html

    def test_renders_all_counties(self):
        html = maps.county_map(self.rows)
        assert 'class="map-figure"' in html
        assert 'Fresno County' in html
        assert 'Kern County' in html      # drawn even with no rows

    def test_shading(self):
        html = maps.county_map(self.rows)
        assert maps.RAMP[-1] in html      # the only county with data gets the darkest step
        assert maps.NO_DATA in html       # a county with no rows is grey

    def test_none_without_geometries(self):
        Region.objects.filter(type='county').update(boundary=None)
        assert maps.county_map(self.rows) is None

    def test_labels_include_pounds(self):
        html = maps.county_map(self.rows)
        assert 'Fresno County: 150 lbs' in html
        assert 'Kern County: no data' in html

    def test_rank_counties_sorts_by_the_metric_and_carries_the_map_colour(self):
        rows = self.rows + [
            {'county_id': 9002, 'county_name': 'Kern County', 'county_slug': 'kern', 'lbs': 20.0, 'acres': 200, 'applications': 1},
        ]
        by_lbs = maps.rank_counties(rows, 'lbs')
        assert [r['county_name'] for r in by_lbs] == ['Fresno County', 'Kern County']
        assert by_lbs[0]['color'] == maps.RAMP[-1] and by_lbs[1]['color'] == maps.RAMP[0]
        by_acres = maps.rank_counties(rows, 'acres')
        assert [r['county_name'] for r in by_acres] == ['Kern County', 'Fresno County']
        # The map shades by the same metric and says so in its labels.
        html = maps.county_map(by_acres, metric='acres')
        assert 'Kern County: 200 acres treated' in html
        assert 'county-legend' not in html
        assert maps.county_metric('nope') == 'lbs' and maps.county_metric('applications') == 'applications'

    def test_labels_are_hover_only(self):
        html = maps.county_map(self.rows)
        assert '"labelOnHover": true' in html
        assert '"labelOnHover": false' not in html
