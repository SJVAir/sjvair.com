from datetime import date, timedelta

from django.test import SimpleTestCase

from camp.utils.charts import line_chart


def days(n, start=date(2026, 8, 1)):
    return [start + timedelta(days=i) for i in range(n)]


class LineChartTests(SimpleTestCase):
    def test_one_path_per_series_and_one_rect_per_band(self):
        svg = line_chart(
            [
                {'label': 'Fresno', 'points': list(zip(days(30), [10.0 + i for i in range(30)])), 'color': '#123456', 'dashed': False},
                {'label': 'County', 'points': list(zip(days(30), [12.0] * 30)), 'color': '#654321', 'dashed': True},
            ],
            bands=[(0, '#00e400'), (9.1, '#ffff00'), (35.5, '#ff7e00')],
        )
        assert svg.count('class="chart-line"') == 2
        assert svg.count('class="chart-band"') == 3
        assert 'stroke-dasharray' in svg
        assert '#123456' in svg and '#654321' in svg
        assert '<svg' in svg and svg.strip().endswith('</svg>')

    def test_gaps_break_the_line(self):
        points = list(zip(days(5), [1.0, 2.0, None, 4.0, 5.0]))
        svg = line_chart([{'label': 'x', 'points': points, 'color': '#000', 'dashed': False}])
        assert svg.count('class="chart-line"') == 2  # two segments

    def test_weekly_ticks_for_short_ranges_and_monthly_for_long(self):
        short = line_chart([{'label': 'x', 'points': list(zip(days(30), [1.0] * 30)), 'color': '#000', 'dashed': False}])
        assert short.count('class="chart-xtick"') == 5  # days 0, 7, 14, 21, 28
        long = line_chart([{'label': 'x', 'points': list(zip(days(120), [1.0] * 120)), 'color': '#000', 'dashed': False}])
        assert long.count('class="chart-xtick"') == 4  # Sep, Oct, Nov, and Aug 1 itself

    def test_empty_and_single_point(self):
        empty = line_chart([{'label': 'x', 'points': [], 'color': '#000', 'dashed': False}])
        assert '<svg' in empty and 'chart-line' not in empty
        single = line_chart([{'label': 'x', 'points': [(date(2026, 8, 1), 3.0)], 'color': '#000', 'dashed': False}])
        assert 'class="chart-point"' in single

    def test_y_axis_covers_data_and_first_band_above_it(self):
        svg = line_chart(
            [{'label': 'x', 'points': list(zip(days(3), [1.0, 2.0, 3.0])), 'color': '#000', 'dashed': False}],
            bands=[(0, '#0f0'), (9.1, '#ff0'), (35.5, '#f70')],
        )
        assert 'class="chart-ytick">20<' in svg
