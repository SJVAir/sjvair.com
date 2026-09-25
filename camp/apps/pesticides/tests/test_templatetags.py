from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from camp.apps.pesticides.templatetags.pesticides_explorer import (
    lbs, month_chart, month_heatmap, sparkline, title_case_name, trend_chart,
)


class LbsFilterTests(SimpleTestCase):
    def test_whole_pounds_with_commas(self):
        assert lbs(26299290.4) == '26,299,290'
        assert lbs(12) == '12'
        assert lbs(0) == '0'
        assert lbs(None) == '—'

    def test_small_amounts_keep_their_decimals(self):
        # A bait at 0.1% active ingredient applies fractions of a pound; that isn't nothing.
        assert lbs(0.186) == '0.19'
        assert lbs(0.0082) == '0.01'
        assert lbs(1.25) == '1.2'
        assert lbs(9.96) == '10.0'


class TitleCaseNameTests(SimpleTestCase):
    def test_all_caps_names_are_title_cased(self):
        assert title_case_name('SELMA HIGH') == 'Selma High'
        assert title_case_name("CHILDREN'S CENTER #2") == "Children's Center #2"

    def test_runs_of_spaces_collapse(self):
        assert title_case_name('KIDS  PRESCHOOL   CENTER') == 'Kids Preschool Center'

    def test_initialisms_and_numerals_stay_upper(self):
        assert title_case_name('FUSD-STOREY') == 'FUSD-Storey'
        assert title_case_name('FRESNO EOC FRANKLIN HEAD START') == 'Fresno EOC Franklin Head Start'
        assert title_case_name("CAMPUS CHILDREN'S CENTER - SITE III") == "Campus Children's Center - Site III"
        assert title_case_name('ABC LEARNING PRESCHOOL & CHILDCARE INC') == 'ABC Learning Preschool & Childcare INC'

    def test_a_trailing_article_moves_to_the_front(self):
        assert title_case_name('LEARNING EXPERIENCE THE') == 'The Learning Experience'

    def test_mixed_case_names_are_left_alone(self):
        assert title_case_name('McKinley Elementary') == 'McKinley Elementary'
        assert title_case_name('de Anza  Academy') == 'de Anza Academy'

    def test_empty(self):
        assert title_case_name('') == ''
        assert title_case_name(None) == ''


class TrendChartTests(SimpleTestCase):
    def rows(self, *pairs, applications=1):
        return [
            {'year': year, 'lbs': lbs, 'acres': 0, 'applications': applications}
            for year, lbs in pairs
        ]

    def test_delta_sentence_reads_previous_then_first_year(self):
        data = trend_chart(self.rows((2023, 88.0), (2022, 100.0), (2014, 128.0)), 2023)
        assert data['sentence'] == 'Down 12% since 2022 · down 31% since 2014'

    def test_delta_sentence_up(self):
        data = trend_chart(self.rows((2023, 150.0), (2022, 100.0), (2014, 100.0)), 2023)
        assert data['sentence'] == 'Up 50% since 2022 · up 50% since 2014'

    def test_delta_sentence_unchanged_below_half_a_percent(self):
        data = trend_chart(self.rows((2023, 100.2), (2022, 100.0), (2014, 100.0)), 2023)
        assert data['sentence'] == 'Unchanged since 2022 · unchanged since 2014'

    def test_delta_sentence_under_all_years_is_the_first_year_only(self):
        data = trend_chart(self.rows((2023, 150.0), (2022, 100.0), (2014, 300.0)), None)
        assert data['sentence'] == 'Down 50% since 2014'
        # No year is being looked at, so no point is emphasised.
        assert data['chart']['selected'] is None

    def test_chart_data_runs_oldest_to_newest_with_the_scope_year_selected(self):
        data = trend_chart(self.rows((2023, 88.0), (2022, 300.0), (2021, 50.0), (2014, 128.0)), 2023)
        assert data['chart'] == {
            'type': 'line', 'unit': 'pounds',
            'x': [2014, 2021, 2022, 2023], 'y': [128.0, 50.0, 300.0, 88.0],
            'selected': 2023,
            'compare': None, 'compare_label': '',
        }
        assert data['has_data'] and data['first_year'] == 2014 and data['last_year'] == 2023
        assert data['chart_id'].startswith('chart-')

    def test_a_scope_year_without_data_selects_nothing(self):
        data = trend_chart(self.rows((2023, 88.0), (2022, 300.0)), 2019)
        assert data['chart']['selected'] is None

    def test_delta_sentence_skips_an_undefined_delta(self):
        data = trend_chart(self.rows((2023, 150.0), (2022, 0.0), (2014, 100.0)), 2023)
        assert data['sentence'] == 'Up 50% since 2014'

    def test_single_year(self):
        data = trend_chart(self.rows((2023, 150.0)), 2023)
        assert data['sentence'] == 'Only one year of data.'

    def test_no_years(self):
        data = trend_chart([], None)
        assert data['has_data'] is False and data['chart']['x'] == []

    def test_title(self):
        data = trend_chart(self.rows((2023, 100.0), (2022, 50.0)), 2023)
        assert data['title'] == 'Lbs applied by year'
        assert data['metric_label'] == 'pounds'

    def test_placeholder_pages_chart_applications(self):
        rows = [
            {'year': 2023, 'lbs': None, 'acres': 0, 'applications': 4},
            {'year': 2022, 'lbs': None, 'acres': 0, 'applications': 2},
        ]
        data = trend_chart(rows, 2023, hide_lbs=True)
        assert data['title'] == 'Applications by year'
        assert data['metric_label'] == 'applications'
        assert data['chart']['unit'] == 'applications'
        assert data['chart']['y'] == [2, 4]
        assert data['sentence'] == 'Up 100% since 2022'

    def test_renders_the_chart_data_for_the_browser(self):
        rows = self.rows((2023, 88.0), (2022, 100.0), (2014, 128.0))
        html = render_to_string('pesticides/includes/trend-chart.html', trend_chart(rows, 2023))
        assert 'class="explorer-chart trend-chart"' in html
        assert 'class="chart-canvas" data-chart="chart-' in html
        # The data rides in a json_script the chart module reads, keyed by the same id.
        assert 'type="application/json"' in html and '"x": [2014, 2022, 2023]' in html
        assert 'Down 12% since 2022 · down 31% since 2014' in html
        assert 'aria-label="Lbs applied by year, 2014 to 2023.' in html
        assert '<svg' not in html

    def test_renders_nothing_without_years(self):
        assert render_to_string('pesticides/includes/trend-chart.html', trend_chart([], None)).strip() == ''


class MonthChartTests(SimpleTestCase):
    def rows(self, *triples):
        return [{'month': month, 'lbs': lbs, 'acres': 0, 'applications': applications} for month, lbs, applications in triples]

    def test_chart_data_is_ordered_by_month_with_labels(self):
        data = month_chart(self.rows((3, 10.5, 2), (1, 0.0, 0), (2, None, 1)), '2023')
        assert data['chart'] == {
            'type': 'bars', 'unit': 'pounds',
            'labels': ['Jan', 'Feb', 'Mar'], 'names': ['January', 'February', 'March'],
            'x': [0, 1, 2], 'y': [0.0, 0, 10.5], 'applications': [0, 1, 2],
        }
        assert data['year_label'] == '2023'

    def test_renders_the_chart_and_a_noscript_table(self):
        html = render_to_string('pesticides/includes/month-chart.html', month_chart(self.rows((8, 1234.0, 7)), '2023'))
        assert 'class="explorer-chart month-chart"' in html
        assert 'aria-label="Lbs applied by month, 2023"' in html
        assert '<noscript>' in html and '<td>August</td>' in html and '1,234' in html


class SparklineTests(SimpleTestCase):
    """
    A leaderboard row's by-year shape, as inline SVG. Each is scaled to its
    own maximum: these say "rising" or "receding", never "bigger than the
    row below".
    """

    def points(self, svg):
        import re

        match = re.search(r'points="([^"]+)"', svg)
        return [tuple(float(n) for n in pair.split(',')) for pair in match.group(1).split()]

    def test_draws_a_point_per_year(self):
        points = self.points(sparkline([1, 2, 3, 4]))
        assert len(points) == 4
        # Spread across the width, in order.
        assert [x for x, _y in points] == sorted(x for x, _y in points)

    def test_the_maximum_sits_at_the_top(self):
        # y grows downward in SVG, so the largest value has the smallest y.
        points = self.points(sparkline([5, 100, 20]))
        assert points[1][1] == min(y for _x, y in points)

    def test_two_series_of_different_magnitude_draw_the_same_shape(self):
        small = self.points(sparkline([1, 2, 1]))
        large = self.points(sparkline([1000, 2000, 1000]))
        assert small == large

    def test_nothing_to_draw(self):
        # A line needs two points to have a shape, and a flat zero would read
        # as a real measurement of nothing.
        assert sparkline([]) == ''
        assert sparkline([5]) == ''
        assert sparkline([0, 0, 0]) == ''
        assert sparkline(None) == ''

    def test_missing_years_are_zeroes_not_gaps(self):
        points = self.points(sparkline([10, 0, 10]))
        assert len(points) == 3
        assert points[1][1] == max(y for _x, y in points)


def grid(*years):
    """`stats.by_year_month()`-shaped rows from (year, [12 lbs]) pairs."""
    return [
        {
            'year': year,
            'months': [{'month': m + 1, 'lbs': value, 'acres': 0, 'applications': 0}
                for m, value in enumerate(values)],
            'lbs': sum(values),
            'applications': 0,
        }
        for year, values in years
    ]


ONE_MONTH = [0] * 2 + [100] + [0] * 9


class MonthHeatmapTests(SimpleTestCase):
    """Months across, years down, shaded by pounds."""

    def cells(self, context, row=0):
        return context['rows'][row]['cells']

    def test_twelve_cells_per_year_newest_row_first(self):
        context = month_heatmap(grid((2023, ONE_MONTH), (2022, ONE_MONTH)))
        assert context['has_data'] is True
        assert [row['year'] for row in context['rows']] == [2023, 2022]
        assert len(self.cells(context)) == 12
        assert context['months'][0] == 'Jan'

    def test_the_scale_is_shared_across_years(self):
        # One grid, one scale: a heavy month in a light year has to read as
        # lighter than the peak, or the rows can't be compared to each other.
        context = month_heatmap(grid((2023, [0, 0, 100] + [0] * 9), (2022, [0, 0, 10] + [0] * 9)))
        assert context['top'] == 100
        assert self.cells(context, 0)[2]['color'] != self.cells(context, 1)[2]['color']

    def test_the_heaviest_cell_takes_the_darkest_class(self):
        context = month_heatmap(grid((2023, ONE_MONTH), (2022, ONE_MONTH)))
        assert self.cells(context)[2]['color'] == context['scale'][-1]

    def test_a_month_with_nothing_reported_is_not_the_palest_class(self):
        # Absent and nearly-nothing are different claims.
        context = month_heatmap(grid((2023, ONE_MONTH), (2022, ONE_MONTH)))
        empty = self.cells(context)[0]
        assert empty['empty'] is True
        assert empty['color'] not in context['scale']

    def test_the_scope_year_is_marked_not_filtered_to(self):
        context = month_heatmap(grid((2023, ONE_MONTH), (2022, ONE_MONTH)), year=2022)
        assert [row['selected'] for row in context['rows']] == [False, True]

    def test_nothing_to_draw(self):
        # One year has no shift to show, and the by-month bars already say
        # everything a single row could.
        assert month_heatmap(grid((2023, ONE_MONTH)))['has_data'] is False
        assert month_heatmap([])['has_data'] is False
        assert month_heatmap(None)['has_data'] is False
        assert month_heatmap(grid((2023, [0] * 12), (2022, [0] * 12)))['has_data'] is False

    def test_renders_a_cell_per_month_with_a_readable_value(self):
        html = render_to_string('pesticides/includes/month-heatmap.html',
            month_heatmap(grid((2023, ONE_MONTH), (2022, ONE_MONTH))))
        assert html.count('class="heatmap-cell') == 24
        assert 'March 2023: 100 lbs' in html

    def test_renders_nothing_for_a_single_year(self):
        html = render_to_string('pesticides/includes/month-heatmap.html',
            month_heatmap(grid((2023, ONE_MONTH))))
        assert html.strip() == ''


class TrendChartComparisonTests(SimpleTestCase):
    """The optional second series: the average valley county, on a county page."""

    def series(self, *years):
        return [{'year': year, 'lbs': value} for year, value in years]

    def test_no_comparison_by_default(self):
        context = trend_chart(self.series((2023, 10), (2022, 20)))
        assert context['chart']['compare'] is None
        assert context['compare_label'] == ''

    def test_the_baseline_is_aligned_to_the_years_of_the_main_series(self):
        context = trend_chart(
            self.series((2023, 10), (2022, 20)),
            compare=self.series((2023, 5), (2022, 6)),
            compare_label='Average valley county')
        assert context['chart']['x'] == [2022, 2023]
        assert context['chart']['compare'] == [6, 5]
        assert context['compare_label'] == 'Average valley county'

    def test_a_year_the_baseline_does_not_cover_is_a_gap_not_a_zero(self):
        # Filling it would draw a baseline dropping to nothing in a year it
        # simply says nothing about.
        context = trend_chart(
            self.series((2023, 10), (2022, 20), (2021, 30)),
            compare=self.series((2023, 5)),
            compare_label='Average valley county')
        assert context['chart']['compare'] == [None, None, 5]

    def test_an_empty_baseline_is_no_baseline(self):
        context = trend_chart(self.series((2023, 10)), compare=[], compare_label='Average valley county')
        assert context['chart']['compare'] is None
        assert context['compare_label'] == ''

    def test_the_legend_names_the_baseline(self):
        html = render_to_string('pesticides/includes/trend-chart.html', trend_chart(
            self.series((2023, 10), (2022, 20)),
            compare=self.series((2023, 5), (2022, 6)),
            compare_label='Average valley county'))
        assert 'Average valley county' in html
        assert 'chart-key is-line' in html


class SparklineLabelTests(TestCase):
    """
    A row's number is the scope year while its sparkline spans every loaded
    year. The line says which, so the two aren't read as the same period.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_the_label_names_the_range(self):
        from camp.apps.pesticides import rollup
        from camp.apps.pesticides.templatetags.pesticides_explorer import series_label
        rollup.rebuild_all()
        assert series_label() == 'Lbs per year, 2022\u20132023'

    def test_the_sparkline_itself_stays_out_of_the_database(self):
        # A pure formatting filter: the board says what the lines cover.
        with self.assertNumQueries(0):
            assert 'polyline' in sparkline([1, 2, 3])

    def test_a_single_loaded_year_reads_as_one_year(self):
        from camp.apps.pesticides import rollup
        from camp.apps.pesticides.models import PesticideUseRollup
        rollup.rebuild_all()
        PesticideUseRollup.objects.filter(year=2022).delete()
        from django.core.cache import cache
        cache.clear()
        from camp.apps.pesticides.templatetags.pesticides_explorer import series_label
        assert series_label() == 'Lbs per year, 2023'

    def test_no_years_loaded_means_no_label(self):
        from camp.apps.pesticides.models import PesticideUseRollup
        PesticideUseRollup.objects.all().delete()
        from django.core.cache import cache
        cache.clear()
        from camp.apps.pesticides.templatetags.pesticides_explorer import series_label
        assert series_label() == ''
