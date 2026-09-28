from django.test import TestCase

from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.templatetags import emissions_explorer as tags


class AmountTests(TestCase):
    def test_tons(self):
        # One decimal everywhere, so a column of values lines up and reads the same.
        nox = POLLUTANTS['nox']
        assert tags.amount(1456.4, nox) == '1,456.4'
        assert tags.amount(214, nox) == '214.0'
        assert tags.amount(8.25, nox) == '8.2'
        assert tags.amount(0.25, nox) == '0.2'
        assert tags.amount(0.001, nox) == '<0.1'
        assert tags.amount(0, nox) == '0.0'
        assert tags.amount(None, nox) == '—'

    def test_quantity(self):
        assert tags.quantity(50547.57) == '50,547.6'
        assert tags.quantity(0.01) == '<0.1'
        assert tags.quantity(None) == '—'

    def test_toxics_convert_to_lbs(self):
        assert tags.amount(0.001, POLLUTANTS['benzene']) == '2.0'


class PercentTests(TestCase):
    def test_percent(self):
        assert tags.percent(0.123) == '12%'
        assert tags.percent(0.004) == '<1%'
        assert tags.percent(0) == '0%'
        assert tags.percent(None) == '—'
        assert tags.width_pct(0.12345) == '12.35%'
        assert tags.signed_pct(100.0) == '+100%'
        assert tags.signed_pct(-62.4) == '−62%'


class TrendChartTests(TestCase):
    def test_chart_payload_and_sentence(self):
        context = tags.emissions_trend_chart(
            [{'year': 2024, 'value': 6.0}, {'year': 2023, 'value': 3.0}], POLLUTANTS['nox'], 2024,
        )
        assert context['chart']['x'] == [2023, 2024]
        assert context['chart']['y'] == [3.0, 6.0]
        assert context['chart']['selected'] == 2024
        assert context['sentence'] == 'Up 100% from 2023'
        assert context['title'] == 'NOx by year (tons/yr)'

    def test_empty(self):
        assert tags.emissions_trend_chart([], POLLUTANTS['nox'])['has_data'] is False


class DairyChartTests(TestCase):
    def test_emissions_chart_readout_notes_the_share(self):
        points = [
            {'year': 2023, 'value': 365.0, 'total': 3650.0, 'share': 0.1},
            {'year': 2022, 'value': 730.0, 'total': 2920.0, 'share': 0.25},
        ]
        context = tags.dairy_emissions_chart(points, POLLUTANTS['rog'], 2023, 'Tulare County')
        chart = context['chart']
        assert (chart['x'], chart['y'], chart['selected'], chart['unit']) == ([2022, 2023], [730.0, 365.0], 2023, 'tons')
        assert chart['notes'] == ['25% of Tulare County ROG', '10% of Tulare County ROG']
        assert context['title'] == 'Dairy cattle ROG, CARB estimate'
        assert context['note'] == 'CARB estimates these from herd counts; its inventory holds years after 2017 at the 2017 level.'
        assert context['note_url'].endswith('#dairies')
        everywhere = tags.dairy_emissions_chart(points, POLLUTANTS['rog'], 2024)
        assert everywhere['chart']['notes'][0] == '25% of the covered counties ROG'
        assert everywhere['chart']['selected'] is None
        assert tags.dairy_emissions_chart([], POLLUTANTS['nox'])['has_data'] is False

    def test_digester_chart(self):
        context = tags.digester_trend_chart([{'year': 2023, 'digesters': 3}, {'year': 2022, 'digesters': 0}], 2023)
        chart = context['chart']
        assert (chart['x'], chart['y'], chart['selected'], chart['whole']) == ([2022, 2023], [0, 3], 2023, True)
        assert context['title'] == 'Dairies with an operating digester'
        assert tags.digester_trend_chart([{'year': 2023, 'digesters': 0}])['has_data'] is False


class SparklineTests(TestCase):
    def test_sparkline(self):
        svg = tags.sparkline([{'year': 2023, 'value': 1.0}, {'year': 2024, 'value': 2.0}])
        assert svg.startswith('<svg class="sparkline"')
        assert '<polyline points="0.0,12.0 100.0,2.0"' in svg
        assert tags.sparkline([{'year': 2024, 'value': 1.0}]) == ''
