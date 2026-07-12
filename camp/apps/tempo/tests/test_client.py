from unittest.mock import MagicMock, patch

import pytest
import requests

from django.test import TestCase, override_settings

from datetime import datetime, timezone as dt_timezone

from camp.apps.tempo.client import TempoClient, _collection_cache


def make_response(status_code=200, json_result=None, content=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.content = content
    response.raise_for_status = MagicMock()
    return response


@override_settings(EARTHDATA_TOKEN='test-token')
class ResolveCollectionsTests(TestCase):
    def setUp(self):
        self.client = TempoClient()
        _collection_cache.clear()

    @patch.object(TempoClient, '_get')
    def test_sorts_newest_version_first(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'feed': {'entry': [
                {'id': 'C-V03', 'version_id': 'V03'},
                {'id': 'C-V04', 'version_id': 'V04'},
            ]}
        })

        collections = self.client._resolve_collections('TEMPO_NO2_L3')

        assert [c['version_id'] for c in collections] == ['V04', 'V03']
        assert [c['concept_id'] for c in collections] == ['C-V04', 'C-V03']

    @patch.object(TempoClient, '_get')
    def test_caches_result_across_calls(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'feed': {'entry': [{'id': 'C-V04', 'version_id': 'V04'}]}
        })

        self.client._resolve_collections('TEMPO_NO2_L3')
        self.client._resolve_collections('TEMPO_NO2_L3')

        assert mock_get.call_count == 1


@override_settings(EARTHDATA_TOKEN='test-token')
class FindGranuleTests(TestCase):
    def setUp(self):
        self.client = TempoClient()
        self.timestamp = datetime(2023, 8, 15, 18, 0, tzinfo=dt_timezone.utc)
        self.bbox = (-121.5, 34.9, -117.9, 38.0)

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_returns_granule_from_newest_collection(self, mock_resolve, mock_search):
        mock_resolve.return_value = [
            {'concept_id': 'C-V04', 'version_id': 'V04'},
            {'concept_id': 'C-V03', 'version_id': 'V03'},
        ]
        mock_search.return_value = {'id': 'G1', 'collection_concept_id': 'C-V04'}

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule == {
            'concept_id': 'G1',
            'granule_id': 'G1',
            'collection_concept_id': 'C-V04',
            'is_final': True,
            'version': 'V04',
        }
        mock_search.assert_called_once_with('C-V04', self.timestamp, self.bbox)

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_falls_back_to_older_collection_when_newest_has_no_granule_yet(self, mock_resolve, mock_search):
        mock_resolve.return_value = [
            {'concept_id': 'C-V04', 'version_id': 'V04'},
            {'concept_id': 'C-V03', 'version_id': 'V03'},
        ]
        mock_search.side_effect = [None, {'id': 'G1', 'collection_concept_id': 'C-V03'}]

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule['version'] == 'V03'
        assert granule['is_final'] is True
        assert mock_search.call_count == 2

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_falls_back_to_nrt_when_no_standard_collection_has_a_granule(self, mock_resolve, mock_search):
        def resolve_side_effect(short_name):
            if short_name == 'TEMPO_NO2_L3':
                return [{'concept_id': 'C-V04', 'version_id': 'V04'}]
            return [{'concept_id': 'C-NRT-V02', 'version_id': 'V02'}]
        mock_resolve.side_effect = resolve_side_effect
        mock_search.side_effect = [None, {'id': 'G1', 'collection_concept_id': 'C-NRT-V02'}]

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule['is_final'] is False
        assert granule['version'] == 'V02'

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_o3tot_never_checks_nrt_since_none_exists(self, mock_resolve, mock_search):
        mock_resolve.return_value = [{'concept_id': 'C-V04', 'version_id': 'V04'}]
        mock_search.return_value = None

        granule = self.client.find_granule('o3tot', self.timestamp, self.bbox)

        assert granule is None
        mock_resolve.assert_called_once_with('TEMPO_O3TOT_L3')

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_returns_none_when_nothing_found_anywhere(self, mock_resolve, mock_search):
        mock_resolve.return_value = [{'concept_id': 'C-V04', 'version_id': 'V04'}]
        mock_search.return_value = None

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule is None


@override_settings(EARTHDATA_TOKEN='test-token')
class FetchGranuleBytesTests(TestCase):
    def setUp(self):
        self.client = TempoClient()
        self.granule = {
            'concept_id': 'G1234-LARC_CLOUD',
            'granule_id': 'G1234-LARC_CLOUD',
            'collection_concept_id': 'C1234-LARC_CLOUD',
            'is_final': True,
        }
        self.bbox = (-121.5, 34.9, -117.9, 38.0)

    @patch.object(TempoClient, '_get')
    def test_returns_subsetted_content(self, mock_get):
        mock_get.return_value = make_response(content=b'netcdf-bytes')

        result = self.client.fetch_granule_bytes(self.granule, self.bbox)

        assert result == b'netcdf-bytes'
        args, kwargs = mock_get.call_args
        assert 'C1234-LARC_CLOUD' in args[0]
        assert kwargs['params']['granuleId'] == 'G1234-LARC_CLOUD'
        assert kwargs['params']['subset'] == ['lat(34.9:38.0)', 'lon(-121.5:-117.9)']
        assert kwargs['allow_redirects'] is True

    @patch.object(TempoClient, '_get')
    def test_raises_for_http_error(self, mock_get):
        response = make_response()
        response.raise_for_status.side_effect = requests.exceptions.HTTPError('500')
        mock_get.return_value = response

        with pytest.raises(requests.exceptions.HTTPError):
            self.client.fetch_granule_bytes(self.granule, self.bbox)
