from datetime import date
from unittest.mock import patch

from django.test import TestCase

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.calheatscore.tasks import get_sjv_zip_regions, import_calheatscore
from camp.apps.regions.models import Region


FRESNO_ROW = {
    'ZIP_CODE': '93728',
    'DATE': '2026-07-11',
    'CHS_Day_0': '2',
    'CHS_Day_1': '3',
    'CHS_Day_2': '1',
    'CHS_Day_3': '0',
    'CHS_Day_4': '4',
    'CHS_Day_5': '2',
    'CHS_Day_6': '2',
}


class GetSJVZipRegionsTests(TestCase):
    fixtures = ['regions']

    def test_returns_zip_inside_sjv_county(self):
        regions = get_sjv_zip_regions()
        assert regions.filter(external_id='93728').exists()

    def test_excludes_non_zipcode_regions(self):
        regions = get_sjv_zip_regions()
        assert not regions.exclude(type=Region.Type.ZIPCODE).exists()

    def test_empty_when_no_counties_loaded(self):
        Region.objects.filter(type=Region.Type.COUNTY).delete()
        regions = get_sjv_zip_regions()
        assert regions.count() == 0


class ImportCalHeatScoreTests(TestCase):
    fixtures = ['regions']

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_creates_seven_days_of_scores(self, mock_client):
        mock_client.query.return_value = [FRESNO_ROW]

        import_calheatscore.call_local()

        scores = CalHeatScore.objects.filter(region__external_id='93728').order_by('date')
        assert scores.count() == 7
        assert scores.first().date == date(2026, 7, 11)
        assert scores.first().score == 2
        assert scores.last().date == date(2026, 7, 17)
        assert scores.last().score == 2

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_skips_unknown_zip_codes(self, mock_client):
        mock_client.query.return_value = [{**FRESNO_ROW, 'ZIP_CODE': '00000'}]

        import_calheatscore.call_local()

        assert CalHeatScore.objects.count() == 0

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_upserts_existing_rows_instead_of_duplicating(self, mock_client):
        mock_client.query.return_value = [FRESNO_ROW]
        import_calheatscore.call_local()
        assert CalHeatScore.objects.filter(region__external_id='93728').count() == 7

        updated_row = {**FRESNO_ROW, 'CHS_Day_0': '4'}
        mock_client.query.return_value = [updated_row]
        import_calheatscore.call_local()

        scores = CalHeatScore.objects.filter(region__external_id='93728')
        assert scores.count() == 7
        assert scores.get(date=date(2026, 7, 11)).score == 4

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_does_not_call_client_when_no_sjv_zip_regions(self, mock_client):
        Region.objects.filter(type=Region.Type.COUNTY).delete()

        import_calheatscore.call_local()

        mock_client.query.assert_not_called()
