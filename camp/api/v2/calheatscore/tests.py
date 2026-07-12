from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.regions.models import Region


class CalHeatScoreListTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_defaults_to_today(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            url = reverse('api:v2:calheatscore:calheatscore-list')
            data = self.client.get(url).json()

        assert data['count'] == 1
        assert data['data'][0]['zipcode'] == '93728'
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


class CalHeatScoreListZipFilterTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def setUp(self):
        # A second ZIP region + score, sharing 2026-07-12 with the fixture's
        # 93728 record, so both can appear on the same date-filtered list.
        self.other_region = Region.objects.create(
            name='93650', slug='93650', type=Region.Type.ZIPCODE, external_id='93650',
        )
        CalHeatScore.objects.create(region=self.other_region, date=date(2026, 7, 12), score=1)

    def test_filters_by_exact_zipcode(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2026-07-12', 'zipcode': '93650'}).json()

        assert data['count'] == 1
        assert data['data'][0]['zipcode'] == '93650'

    def test_filters_by_zipcode_in(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2026-07-12', 'zipcode__in': '93728,93650'}).json()

        assert data['count'] == 2
        zips = {row['zipcode'] for row in data['data']}
        assert zips == {'93728', '93650'}

    def test_zipcode_in_excludes_unlisted_zips(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2026-07-12', 'zipcode__in': '93650'}).json()

        assert data['count'] == 1
        assert data['data'][0]['zipcode'] == '93650'


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

    def test_filters_by_exact_date(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '93728'})
        data = self.client.get(url, {'date': '2026-07-12'}).json()

        assert data['count'] == 1
        assert data['data'][0]['date'] == '2026-07-12'

    def test_filters_by_date_range(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '93728'})
        data = self.client.get(url, {'date__gte': '2026-07-12'}).json()

        assert data['count'] == 2
        dates = {row['date'] for row in data['data']}
        assert dates == {'2026-07-12', '2026-07-13'}
