from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class CalHeatScoreListTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_defaults_to_today(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            url = reverse('api:v2:calheatscore:calheatscore-list')
            data = self.client.get(url).json()

        assert data['count'] == 1
        assert data['data'][0]['zip_code'] == '93728'
        assert data['data'][0]['score'] == 3
        assert data['data'][0]['score_display'] == 'High'

    def test_explicit_date_overrides_default(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2026-07-13'}).json()

        assert data['count'] == 1
        assert data['data'][0]['score'] == 1

    def test_no_results_for_date_with_no_data(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2099-01-01'}).json()

        assert data['count'] == 0


class CalHeatScoreByZipTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_returns_all_dates_for_zip_newest_first(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '93728'})
        data = self.client.get(url).json()

        assert data['count'] == 3
        dates = [row['date'] for row in data['data']]
        assert dates == ['2026-07-13', '2026-07-12', '2026-07-11']

    def test_empty_for_unknown_zip(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '00000'})
        data = self.client.get(url).json()

        assert data['count'] == 0
