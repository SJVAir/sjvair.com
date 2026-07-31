from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests

from camp.apps.monitors.airnow.client import AirNowClient


def make_response(status_code=200, json_result=None, json_error=None):
    response = MagicMock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = json_result
    return response


class FetchEntriesTests(TestCase):
    def setUp(self):
        self.client = AirNowClient(api_key='test-key')

    @patch('camp.apps.monitors.airnow.client.time.sleep')
    @patch.object(AirNowClient, 'data')
    def test_returns_entries_on_first_success(self, mock_data, mock_sleep):
        mock_data.return_value = make_response(json_result=[{'SiteName': 'A'}])

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'A'}]
        assert mock_data.call_count == 1
        mock_sleep.assert_not_called()

    @patch('camp.apps.monitors.airnow.client.time.sleep')
    @patch.object(AirNowClient, 'data')
    def test_retries_on_bad_json_body_then_succeeds(self, mock_data, mock_sleep):
        json_error = requests.exceptions.JSONDecodeError('Expecting value', '', 0)
        mock_data.side_effect = [
            make_response(json_error=json_error),
            make_response(json_result=[{'SiteName': 'B'}]),
        ]

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'B'}]
        assert mock_data.call_count == 2
        mock_sleep.assert_called_once()

    @patch('camp.apps.monitors.airnow.client.time.sleep')
    @patch.object(AirNowClient, 'data')
    def test_raises_after_exhausting_attempts_on_bad_json(self, mock_data, mock_sleep):
        json_error = requests.exceptions.JSONDecodeError('Expecting value', '', 0)
        mock_data.return_value = make_response(json_error=json_error)

        with self.assertRaises(requests.exceptions.JSONDecodeError):
            self.client.fetch_entries(
                bbox=(1, 2, 3, 4), start_date=None, end_date=None, max_attempts=3,
            )

        assert mock_data.call_count == 3

    @patch('camp.apps.monitors.airnow.client.time.sleep')
    @patch.object(AirNowClient, 'data')
    def test_retries_on_rate_limit_then_succeeds(self, mock_data, mock_sleep):
        mock_data.side_effect = [
            make_response(status_code=429),
            make_response(json_result=[{'SiteName': 'C'}]),
        ]

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'C'}]
        assert mock_data.call_count == 2
        mock_sleep.assert_called_once()

    @patch('camp.apps.monitors.airnow.client.time.sleep')
    @patch.object(AirNowClient, 'data')
    def test_raises_after_exhausting_attempts_on_rate_limit(self, mock_data, mock_sleep):
        response = make_response(status_code=429)
        response.raise_for_status.side_effect = requests.exceptions.HTTPError('429')
        mock_data.return_value = response

        with self.assertRaises(requests.exceptions.HTTPError):
            self.client.fetch_entries(
                bbox=(1, 2, 3, 4), start_date=None, end_date=None, max_attempts=2,
            )

        assert mock_data.call_count == 2
