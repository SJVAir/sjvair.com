from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.ces import endpoints
from camp.utils.test import get_response_data

ces4_list = endpoints.CES4List.as_view()
ces4_detail = endpoints.CES4Detail.as_view()


class CES4EndpointTests(TestCase):
    fixtures = ['calenviroscreen']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_2020_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list', kwargs={'year': '2020'})
        request = self.factory.get(url)
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_2010_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list', kwargs={'year': '2010'})
        request = self.factory.get(url)
        response = ces4_list(request, year='2010')
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_records_have_expected_fields(self):
        request = self.factory.get('/')
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        record = data['data'][0]
        assert 'tract' in record
        assert 'census_year' in record
        assert 'ci_score' in record
        assert 'ci_score_p' in record
        assert 'dac_sb535' in record
        assert 'pollution_p' in record
        assert 'popchar_p' in record

    def test_list_census_year_matches_requested_year(self):
        request = self.factory.get('/')
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        assert all(r['census_year'] == '2020' for r in data['data'])

    def test_detail_returns_correct_tract(self):
        tract = '06019000101'
        request = self.factory.get('/')
        response = ces4_detail(request, year='2020', tract=tract)
        data = get_response_data(response)

        assert response.status_code == 200
        assert data['data']['tract'] == tract
        assert data['data']['census_year'] == '2020'

    def test_detail_404_for_unknown_tract(self):
        request = self.factory.get('/')
        response = ces4_detail(request, year='2020', tract='99999999999')

        assert response.status_code == 404

    def test_detail_404_for_wrong_year(self):
        # tract exists for 2020 but requesting 2030
        request = self.factory.get('/')
        response = ces4_detail(request, year='2030', tract='06019000101')

        assert response.status_code == 404

    def test_filter_by_dac_sb535(self):
        request = self.factory.get('/', {'dac_sb535': 'true'})
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 1
        assert data['data'][0]['dac_sb535'] is True

    def test_filter_by_ci_score_p_gte(self):
        request = self.factory.get('/', {'ci_score_p__gte': '80'})
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        assert response.status_code == 200
        assert all(r['ci_score_p'] >= 80 for r in data['data'])
