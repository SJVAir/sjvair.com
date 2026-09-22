from django.test import TestCase

from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.templatetags import emissions_explorer as tags


class AmountTests(TestCase):
    def test_tons(self):
        nox = POLLUTANTS['nox']
        assert tags.amount(1456.4, nox) == '1,456'
        assert tags.amount(8.25, nox) == '8.2'
        assert tags.amount(0.25, nox) == '0.25'
        assert tags.amount(0.001, nox) == '<0.01'
        assert tags.amount(0, nox) == '0'
        assert tags.amount(None, nox) == '—'

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


class SparklineTests(TestCase):
    def test_sparkline(self):
        svg = tags.sparkline([{'year': 2023, 'value': 1.0}, {'year': 2024, 'value': 2.0}])
        assert svg.startswith('<svg class="sparkline"')
        assert '<polyline points="0.0,12.0 100.0,2.0"' in svg
        assert tags.sparkline([{'year': 2024, 'value': 1.0}]) == ''
