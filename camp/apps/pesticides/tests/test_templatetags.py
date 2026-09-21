from django.template.loader import render_to_string
from django.test import SimpleTestCase

from camp.apps.pesticides.templatetags.pesticides_explorer import lbs, trend_chart


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

    def test_delta_sentence_skips_an_undefined_delta(self):
        data = trend_chart(self.rows((2023, 150.0), (2022, 0.0), (2014, 100.0)), 2023)
        assert data['sentence'] == 'Up 50% since 2014'

    def test_single_year(self):
        data = trend_chart(self.rows((2023, 150.0)), 2023)
        assert data['sentence'] == 'Only one year loaded'

    def test_no_years(self):
        assert trend_chart([], None)['points'] == []

    def test_geometry_and_title(self):
        data = trend_chart(self.rows((2023, 100.0), (2022, 50.0)), 2023)
        assert data['title'] == 'Pounds applied by year'
        assert data['polyline'] == '6.0,45.0 314.0,6.0'
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
        # Year labels at both ends.
        assert '>2014<' in html and '>2023<' in html

    def test_renders_nothing_without_years(self):
        assert render_to_string('pesticides/includes/trend-chart.html', trend_chart([], None)).strip() == ''
