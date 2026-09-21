from django.template.loader import render_to_string
from django.test import SimpleTestCase

from camp.apps.pesticides.templatetags.pesticides_explorer import lbs, month_chart, title_case_name, trend_chart


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
