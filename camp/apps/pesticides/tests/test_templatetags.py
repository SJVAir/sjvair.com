from django.template.loader import render_to_string
from django.test import SimpleTestCase

from camp.apps.pesticides.templatetags.pesticides_explorer import compact, lbs, title_case_name, trend_chart


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
        assert not any(point['is_selected'] for point in data['points'])

    def test_first_last_and_highest_values_are_written_on_the_chart(self):
        data = trend_chart(self.rows((2023, 88.0), (2022, 300.0), (2021, 50.0), (2014, 128.0)), 2023)
        assert [(p['year'], p['label']) for p in data['points']] == [
            (2014, '128'), (2021, ''), (2022, '300'), (2023, '88'),
        ]
        assert [p['anchor'] for p in data['points']] == ['start', 'middle', 'middle', 'end']

    def test_labels_sit_above_their_points_even_at_the_peak(self):
        # The first year is the highest: its label still goes above the
        # point, into the label band, rather than down onto the line.
        data = trend_chart(self.rows((2023, 88.0), (2022, 100.0), (2014, 128.0)), 2023)
        first = data['points'][0]
        assert first['y'] == 18.0
        assert first['label_y'] == 11.0 and first['label_x'] == first['x']
        assert all(p['label_y'] < p['y'] for p in data['points'])

    def test_big_values_are_written_compactly(self):
        data = trend_chart(self.rows((2023, 88_508_098.0), (2022, 45_210.0), (2014, 106_857_127.0)), 2023)
        assert [p['label'] for p in data['points']] == ['107M', '', '88.5M']
        # The full number stays on the hover.
        assert data['points'][0]['display'] == '106,857,127'

    def test_compact(self):
        assert compact(4607.0) == '4,607'
        assert compact(0.19) == '0.19'
        assert compact(45_210.0) == '45.2k'
        assert compact(452_100.0) == '452k'
        assert compact(8_900_000.0) == '8.9M'
        assert compact(107_000_000.0) == '107M'
        assert compact(12, hide_lbs=True) == '12'
        assert compact(None) == '—'

    def test_delta_sentence_skips_an_undefined_delta(self):
        data = trend_chart(self.rows((2023, 150.0), (2022, 0.0), (2014, 100.0)), 2023)
        assert data['sentence'] == 'Up 50% since 2014'

    def test_single_year(self):
        data = trend_chart(self.rows((2023, 150.0)), 2023)
        assert data['sentence'] == 'Only one year of data.'

    def test_no_years(self):
        assert trend_chart([], None)['points'] == []

    def test_geometry_and_title(self):
        data = trend_chart(self.rows((2023, 100.0), (2022, 50.0)), 2023)
        assert data['title'] == 'Lbs applied by year'
        # The plot stops 18 units short of the top: that band holds the labels.
        assert data['polyline'] == '6.0,51.0 314.0,18.0'
        assert [p['year'] for p in data['points']] == [2022, 2023]
        assert [p['is_selected'] for p in data['points']] == [False, True]
        assert data['first_year'] == 2022 and data['last_year'] == 2023

    def test_placeholder_pages_chart_applications(self):
        rows = [
            {'year': 2023, 'lbs': None, 'acres': 0, 'applications': 4},
            {'year': 2022, 'lbs': None, 'acres': 0, 'applications': 2},
        ]
        data = trend_chart(rows, 2023, hide_lbs=True)
        assert data['title'] == 'Applications by year'
        assert data['metric_label'] == 'applications'
        assert [p['value'] for p in data['points']] == [2, 4]
        assert data['sentence'] == 'Up 100% since 2022'

    def test_renders_an_inline_svg(self):
        rows = self.rows((2023, 88.0), (2022, 100.0), (2014, 128.0))
        html = render_to_string('pesticides/includes/trend-chart.html', trend_chart(rows, 2023))
        assert '<svg' in html and 'viewBox="0 0 320 90"' in html
        assert '<polyline' in html and '<circle' in html
        assert 'Down 12% since 2022 · down 31% since 2014' in html
        # Year labels at both ends, and the values on the points.
        assert '>2014<' in html and '>2023<' in html
        assert 'trend-value' in html and '>128<' in html and '>88<' in html

    def test_renders_nothing_without_years(self):
        assert render_to_string('pesticides/includes/trend-chart.html', trend_chart([], None)).strip() == ''
