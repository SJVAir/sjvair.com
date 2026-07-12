from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

from camp.apps.calheatscore.client import CalHeatScoreClient, CalHeatScoreError


def make_response(json_result=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.raise_for_status = MagicMock()
    return response


class CalHeatScoreClientTests(TestCase):
    def setUp(self):
        self.client = CalHeatScoreClient()

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_returns_feature_attributes(self, mock_data):
        mock_data.return_value = make_response(json_result={
            'features': [
                {'attributes': {'ZIP_CODE': '93728', 'DATE': '2026-07-11', 'CHS_Day_0': '2'}},
            ],
        })

        rows = self.client.query(['93728'])

        assert rows == [{'ZIP_CODE': '93728', 'DATE': '2026-07-11', 'CHS_Day_0': '2'}]
        mock_data.assert_called_once_with(['93728'])

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_returns_empty_list_for_empty_input(self, mock_data):
        rows = self.client.query([])

        assert rows == []
        mock_data.assert_not_called()

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_raises_on_error_property(self, mock_data):
        mock_data.return_value = make_response(json_result={
            'error': {'code': 400, 'message': 'Invalid where clause'},
        })

        with pytest.raises(CalHeatScoreError):
            self.client.query(['93728'])

    def test_data_builds_where_clause_and_params(self):
        with patch.object(self.client.session, 'get') as mock_get:
            mock_get.return_value = make_response(json_result={'features': []})
            self.client.data(['93728', '93650'])

        args, kwargs = mock_get.call_args
        assert args[0] == CalHeatScoreClient.url
        params = kwargs['params']
        assert params['where'] == "ZIP_CODE IN ('93728','93650')"
        assert params['returnGeometry'] == 'false'
        assert params['f'] == 'json'
        assert 'CHS_Day_0' in params['outFields']
        assert 'CHS_Day_6' in params['outFields']
