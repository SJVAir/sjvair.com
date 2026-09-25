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


class DivergingClassTests(TestCase):
    def test_breaks_mirror_around_zero(self):
        classes = maps.diverging_classes({'a': -100.0, 'b': -10.0, 'c': 10.0, 'd': 100.0})
        assert classes.breaks == sorted(classes.breaks)
        negative = [b for b in classes.breaks if b < 0]
        positive = [b for b in classes.breaks if b > 0]
        assert sorted(abs(b) for b in negative) == sorted(positive)
        assert 0.0 in classes.breaks

    def test_equal_magnitudes_sit_the_same_distance_from_the_centre(self):
        classes = maps.diverging_classes({'a': -100.0, 'b': -10.0, 'c': 10.0, 'd': 100.0})
        centre = classes.breaks.index(0.0)
        assert centre - classes.index_for(-100.0) == classes.index_for(100.0) - centre
        assert centre - classes.index_for(-10.0) == classes.index_for(10.0) - centre

    def test_three_states_are_distinct(self):
        classes = maps.diverging_classes({'a': -50.0, 'b': 0.0, 'c': 50.0, 'd': None})
        # No data, no change, and a real change are three different things.
        assert classes.color_for(None) == maps.NO_DATA
        assert classes.color_for(0.0) != maps.NO_DATA
        assert classes.color_for(0.0) != classes.color_for(50.0)
        assert classes.color_for(-50.0) != classes.color_for(50.0)

    def test_decreases_and_increases_take_opposite_ends(self):
        ramp = maps.DIVERGING_RAMPS['rdbu']
        classes = maps.diverging_classes({'a': -100.0, 'b': 100.0})
        assert classes.color_for(-100.0) == ramp[0]
        assert classes.color_for(100.0) == ramp[-1]

    def test_no_duplicate_colours_at_the_default_class_count(self):
        # CLASSES is 8 against a seven-stop ramp -- four a side from a
        # four-stop half -- so the colours have to be interpolated.
        values = {i: float(i - 8) * 10 for i in range(1, 16)}
        classes = maps.diverging_classes(values)
        assert len(set(classes.colors)) == len(classes.colors)

    def test_the_smallest_change_is_not_read_as_no_change(self):
        # More distinct magnitudes than classes, so the quantile bounds skip
        # the smallest one. Mirroring the break values drops everything below
        # the first bound into the neutral class, which would paint the
        # smallest decrease on the map as "no change".
        deltas = {i: float(-i * 1000) for i in range(1, 12)}
        classes = maps.diverging_classes(deltas)
        neutral = maps.DIVERGING_RAMP[maps.DIVERGING_CENTER]
        for key, delta in deltas.items():
            assert classes.color_for(delta) != neutral, f'{delta} was graded as no change'
        # ...and the smallest decrease is still the palest of them.
        assert classes.index_for(-1000.0) == classes.neutral_index - 1
        assert classes.index_for(-11000.0) == 0

    def test_every_class_is_reachable_from_both_sides(self):
        deltas = {i: float(i - 6) * 1000 for i in range(1, 12) if i != 6}
        classes = maps.diverging_classes(deltas)
        used = {classes.index_for(d) for d in deltas.values()}
        assert used == set(range(len(classes.colors))) - {classes.neutral_index}

    def test_degenerate_inputs(self):
        assert maps.diverging_classes({}).breaks == []
        assert maps.diverging_classes({}).color_for(None) == maps.NO_DATA
        # Every delta zero: nothing to grade, but zero is still "no change".
        flat = maps.diverging_classes({'a': 0.0, 'b': 0.0})
        assert flat.color_for(0.0) != maps.NO_DATA
        assert maps.diverging_classes({'a': None}).color_for(None) == maps.NO_DATA

    def test_a_single_magnitude(self):
        classes = maps.diverging_classes({'a': -5.0, 'b': 5.0})
        assert classes.color_for(-5.0) != classes.color_for(5.0)
        assert classes.color_for(0.0) not in (classes.color_for(-5.0), classes.color_for(5.0))

    def test_legend_covers_every_class(self):
        classes = maps.diverging_classes({'a': -100.0, 'b': -10.0, 'c': 0.0, 'd': 10.0, 'e': 100.0})
        legend = classes.legend()
        assert len(legend) == len(classes.breaks)
        for row in legend:
            assert row['low'] <= row['high']

    def test_diverging_ramp_for_refuses_a_sequential_name(self):
        assert maps.diverging_ramp_for('brbg') == maps.DIVERGING_RAMPS['brbg']
        # 'blues' is sequential: a diff map must not be drawn one-sided.
        assert maps.diverging_ramp_for('blues') == maps.DIVERGING_RAMP
        assert maps.diverging_ramp_for(None) == maps.DIVERGING_RAMP
        assert maps.diverging_ramp_for('nonsense') == maps.DIVERGING_RAMP


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

    def test_compare_shades_the_change_with_a_diverging_ramp(self):
        previous = [{**self.rows[0], 'lbs': 50.0}]
        html = maps.county_map(self.rows, compare_by_county=previous)
        # Fresno rose 150 - 50; the increase takes the ramp's far end.
        assert maps.DIVERGING_RAMP[-1] in html
        # ...and none of the sequential ramp is used for a change map.
        assert maps.RAMP[-1] not in html

    def test_compare_distinguishes_no_change_from_no_data(self):
        previous = [{**self.rows[0]}]      # identical totals: no change
        html = maps.county_map(self.rows, compare_by_county=previous)
        neutral = maps.DIVERGING_RAMP[maps.DIVERGING_CENTER]
        assert neutral in html             # Fresno didn't move
        assert maps.NO_DATA in html        # Kern has no rows in either year

    def test_compare_labels_name_the_change(self):
        previous = [{**self.rows[0], 'lbs': 50.0}]
        html = maps.county_map(self.rows, compare_by_county=previous)
        assert 'Fresno County: +100 lbs' in html
        assert 'Kern County: no data' in html

    def test_compare_labels_a_decrease_with_its_sign(self):
        previous = [{**self.rows[0], 'lbs': 400.0}]
        html = maps.county_map(self.rows, compare_by_county=previous)
        assert 'Fresno County: -250 lbs' in html

    def test_compare_counts_a_county_new_in_the_scope_year(self):
        # No rows in the compared year is a rise from nothing, not no data.
        html = maps.county_map(self.rows, compare_by_county=[])
        assert maps.NO_DATA not in html.split('Kern County')[0].split('Fresno County')[-1]
        assert 'Fresno County: +150 lbs' in html

    def test_without_compare_the_figure_stays_sequential(self):
        # Each render mints its own payload id, so compare what it shades
        # with rather than the bytes.
        html = maps.county_map(self.rows, compare_by_county=None)
        assert maps.RAMP[-1] in html
        assert not any(color in html for color in maps.DIVERGING_RAMP)
        assert 'Fresno County: 150 lbs' in html

    def test_rank_counties_carries_the_diverging_colour(self):
        previous = [{**self.rows[0], 'lbs': 50.0}]
        ranked = maps.rank_counties(self.rows, compare_by_county=previous)
        fresno = next(row for row in ranked if row['county_id'] == 9001)
        assert fresno['change'] == 100.0
        assert fresno['color'] == maps.DIVERGING_RAMP[-1]

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
