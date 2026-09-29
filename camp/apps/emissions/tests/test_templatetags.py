from django.test import TestCase

from camp.apps.emissions.pollutants import CANCER, POLLUTANTS, toxic_pollutant
from camp.apps.emissions.templatetags import emissions_explorer as tags
from camp.apps.emissions.templatetags.emissions_explorer import amount, share_pct


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

    def test_toxics_are_already_in_lbs(self):
        benzene = toxic_pollutant({'pk': 1, 'slug': 'benzene', 'name': 'Benzene'})
        assert tags.amount(2.0, benzene) == '2.0'


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
        assert context['note'] == 'Animals and manure only: CARB counts feed and silage, dairies’ larger ROG source, separately. Years after 2017 are CARB projections.'
        assert context['note_url'].endswith('#dairies')
        everywhere = tags.dairy_emissions_chart(points, POLLUTANTS['rog'], 2024)
        assert everywhere['chart']['notes'][0] == '25% of the covered counties ROG'
        assert everywhere['chart']['selected'] is None
        assert tags.dairy_emissions_chart([], POLLUTANTS['nox'])['has_data'] is False

    def test_emissions_chart_notes_a_flat_estimate(self):
        points = [{'year': year, 'value': 3.0 if year > 2011 else 4.0, 'total': 30.0, 'share': 0.1} for year in range(2010, 2016)]
        note = tags.dairy_emissions_chart(points, POLLUTANTS['rog'])['note']
        assert note.endswith('Years after 2017 are CARB projections; its estimate is the same every year since 2012.')

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


class SharePctTests(TestCase):
    def test_formats(self):
        assert share_pct(None) == '—' and share_pct(0) == '0%'
        assert share_pct(0.00005) == '<0.01%' and share_pct(0.0003) == '0.03%'
        assert share_pct(0.012) == '1.2%' and share_pct(0.2437) == '24%' and share_pct(1) == '100%'
        assert amount(0.012, CANCER) == '1.2%' and amount(2, POLLUTANTS['nox']) == '2.0'


class PercentileTests(TestCase):
    def test_rounds_down_so_no_tract_reads_100th(self):
        assert tags.percentile(99.989) == '99th'
        assert tags.percentile(89.6) == '89th'
        assert tags.percentile(1.36) == '1st'
        assert tags.percentile(0.4) == '1st'
        assert tags.percentile(None) == ''
