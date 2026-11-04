from datetime import date
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.regions.models import Region
from camp.apps.regions.tests.test_resolve import make_region


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

    def test_empty_date_keeps_the_default(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            url = reverse('api:v2:calheatscore:calheatscore-list')
            data = self.client.get(url, {'date': ''}).json()
        assert [r['date'] for r in data['data']] == ['2026-07-12']

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


class CalHeatScoreMetaTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def get_scale(self):
        response = self.client.get(reverse('api:v2:calheatscore:calheatscore-meta'))
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=3600'
        return response.json()['data']['scales']['heat-score']

    def test_heat_meta(self):
        scale = self.get_scale()
        levels = scale['levels']
        assert [l['key'] for l in levels] == ['low', 'mild', 'moderate', 'high', 'severe']
        assert [l['tier'] for l in levels] == [0, 1, 2, 3, 4]
        assert [l['value'] for l in levels] == [0, 1, 2, 3, 4]
        assert scale['label'] == 'Heat Score'
        assert scale['kind'] == 'category'
        assert levels[3]['color'] == '#c23a00'
        assert levels[0]['guidance'] == ''
        assert levels[4]['guidance'].startswith('Everyone should stay somewhere cool')

    def test_meta_routes_not_shadowed(self):
        response = self.client.get('/api/2.0/calheatscore/meta/')
        assert 'heat-score' in response.json()['data']['scales']


class CalHeatScorePlaceTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def setUp(self):
        self.url = reverse('api:v2:calheatscore:calheatscore-place')
        self.zip_a = Region.objects.get(external_id='93728')
        self.zip_b = Region.objects.create(
            name='93650', slug='93650', type=Region.Type.ZIPCODE, external_id='93650',
        )
        self.zip_c = Region.objects.create(
            name='93610', slug='93610', type=Region.Type.ZIPCODE, external_id='93610',
        )

    def get(self, zips, params=None):
        params = {'region_type': 'county', 'region': '06019', 'date__gte': '2026-07-01', **(params or {})}
        with patch('camp.api.v2.calheatscore.endpoints.zips_for', return_value=zips):
            return self.client.get(self.url, params)

    def test_county_takes_highest_zip(self):
        CalHeatScore.objects.create(region=self.zip_b, date=date(2026, 7, 12), score=1)
        CalHeatScore.objects.create(region=self.zip_c, date=date(2026, 7, 12), score=4)
        response = self.get([self.zip_a, self.zip_b, self.zip_c], {'date': '2026-07-12'})
        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=900'
        body = response.json()['data']
        assert body['place'] == {'region': {'type': 'county', 'external_id': '06019', 'name': 'Fresno County'}}
        assert body['zip_count'] == 3
        assert body['days'] == [
            {'date': '2026-07-12', 'score': 4, 'score_display': 'Severe', 'zipcode': '93610'},
        ]

    def test_highest_score_wins_per_date(self):
        CalHeatScore.objects.create(region=self.zip_b, date=date(2026, 7, 11), score=4)
        days = self.get([self.zip_a, self.zip_b]).json()['data']['days']
        assert [d['date'] for d in days] == ['2026-07-11', '2026-07-12', '2026-07-13']
        assert days[0] == {'date': '2026-07-11', 'score': 4, 'score_display': 'Severe', 'zipcode': '93650'}
        assert days[1]['zipcode'] == '93728'

    def test_tie_lowest_zip(self):
        CalHeatScore.objects.create(region=self.zip_b, date=date(2026, 7, 12), score=3)
        days = self.get([self.zip_a, self.zip_b], {'date': '2026-07-12'}).json()['data']['days']
        assert days == [{'date': '2026-07-12', 'score': 3, 'score_display': 'High', 'zipcode': '93650'}]

    def test_zip_target_is_itself(self):
        response = self.client.get(self.url, {
            'region_type': 'zipcode', 'region': '93728', 'date__gte': '2026-07-01',
        })
        body = response.json()['data']
        assert body['zip_count'] == 1
        assert [d['score'] for d in body['days']] == [2, 3, 1]

    def test_no_rows_is_empty(self):
        response = self.get([self.zip_a], {'date__gte': '2099-01-01'})
        assert response.status_code == 200
        assert response.json()['data']['days'] == []

    def test_defaults_to_today_onward(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            response = self.client.get(self.url, {'region_type': 'zipcode', 'region': '93728'})
        assert [d['date'] for d in response.json()['data']['days']] == ['2026-07-12', '2026-07-13']

    def test_empty_date_params_keep_the_default(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            response = self.client.get(self.url, {
                'region_type': 'zipcode', 'region': '93728', 'date': '', 'date__gte': ''})
        assert [d['date'] for d in response.json()['data']['days']] == ['2026-07-12', '2026-07-13']

    def test_errors_pass_through(self):
        response = self.client.get(self.url, {'region_type': 'land_use', 'region': '1'})
        assert response.status_code == 400
        response = self.client.get(self.url, {'region_type': 'county', 'region': 'nope'})
        assert response.status_code == 404
        assert self.client.get(self.url).status_code == 400

    def test_retired_region_still_answers(self):
        self.zip_a.retired_at = timezone.now()
        self.zip_a.save()
        response = self.client.get(self.url, {
            'region_type': 'zipcode', 'region': '93728', 'date__gte': '2026-07-01',
        })
        assert response.status_code == 200
        assert len(response.json()['data']['days']) == 3

    def test_query_count_bounded(self):
        # Mocked place: only the region lookup and the one score query remain.
        with self.assertNumQueries(2):
            self.get([self.zip_a])
        with self.assertNumQueries(2):
            self.get([self.zip_a, self.zip_b, self.zip_c])

    def test_query_count_independent_of_zip_count_cold(self):
        counts = []
        for n in (1, 6):
            cache.clear()
            county = make_region(f'Box {n}', Region.Type.COUNTY, f'box{n}', (n * 100, 0, n * 100 + 10, 10))
            for i in range(n):
                zipcode = make_region(
                    f'Z{n}{i}', Region.Type.ZIPCODE, f'9{n}{i:03d}',
                    (n * 100 + i, 1, n * 100 + i + 0.5, 2))
                CalHeatScore.objects.create(region=zipcode, date=date(2026, 7, 12), score=i % 5)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url, {
                    'region_type': 'county', 'region': county.external_id, 'date': '2026-07-12'})
            body = response.json()['data']
            assert body['zip_count'] == n
            assert len(body['days']) == 1
            counts.append(len(queries))
        assert counts[0] == counts[1]
        assert counts[1] <= 4

    def test_monitor_target(self):
        make_region('Mon Zip', Region.Type.ZIPCODE, '90020', (-100, 30, -99, 31))
        zipcode = Region.objects.get(external_id='90020')
        CalHeatScore.objects.create(region=zipcode, date=date(2026, 7, 12), score=4)
        monitor = CIMIS.objects.create(
            name='In', station_number='7', position=Point(-99.5, 30.5, srid=4326),
            location=CIMIS.LOCATION.outside)
        response = self.client.get(self.url, {'monitor': str(monitor.pk), 'date__gte': '2026-07-01'})
        body = response.json()['data']
        assert body['place'] == {'monitor': str(monitor.pk)}
        assert body['zip_count'] == 1
        assert body['days'] == [
            {'date': '2026-07-12', 'score': 4, 'score_display': 'Severe', 'zipcode': '90020'}]

    def test_monitor_without_position(self):
        monitor = CIMIS.objects.create(
            name='No Pos', station_number='9', position=None, location=CIMIS.LOCATION.outside)
        response = self.client.get(self.url, {'monitor': str(monitor.pk)})
        assert response.status_code == 400
        assert response.json()['error'] == 'Monitor has no location.'

    def test_hidden_monitor_404(self):
        monitor = CIMIS.objects.create(
            name='Hidden', station_number='8', position=Point(-99.5, 30.5, srid=4326),
            location=CIMIS.LOCATION.outside, is_hidden=True)
        response = self.client.get(self.url, {'monitor': str(monitor.pk)})
        assert response.status_code == 404

    def test_zip_filters_are_ignored(self):
        CalHeatScore.objects.create(region=self.zip_b, date=date(2026, 7, 12), score=4)
        zips = [self.zip_a, self.zip_b]
        plain = self.get(zips).json()['data']
        filtered = self.get(zips, {'zipcode': '93728', 'zipcode__in': '93728'}).json()['data']
        assert filtered == plain
