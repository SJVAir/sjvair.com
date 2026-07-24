from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from camp.apps.tempo.models import Granule
from camp.apps.tempo.parsing import GranuleData
from camp.apps.tempo.sync import sync_granule


FIXED_BBOX = (-121.5, 34.9, -117.9, 38.0)


def make_granule_data(version='V03'):
    import numpy as np
    return GranuleData(
        array=np.array([[1.0e16, 2.0e16], [3.0e16, 4.0e16]]),
        lon_min=-120.0, lat_min=36.96, lon_max=-119.96, lat_max=37.0,
        version=version,
    )


def make_granule_meta(concept_id='G1', collection_id='C1', is_final=True, version='V03'):
    return {
        'concept_id': concept_id, 'granule_id': concept_id,
        'collection_concept_id': collection_id, 'is_final': is_final, 'version': version,
    }


@patch('camp.apps.tempo.sync.load_region_geometry')
class SyncGranuleTests(TestCase):
    def setUp(self):
        self.timestamp = datetime(2023, 8, 15, 18, 0, tzinfo=dt_timezone.utc)

    def _mock_geometry(self, mock_load_region_geometry):
        geometry = MagicMock()
        geometry.bounds = FIXED_BBOX
        mock_load_region_geometry.return_value = geometry

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_creates_new_granule(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)
        mock_parse.return_value = make_granule_data(version='V03')

        client = MagicMock()
        client.find_granule.return_value = make_granule_meta(is_final=False, version='V03')
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        assert result.version == 'V03'
        assert result.is_final is False

    def test_returns_none_when_nasa_has_no_granule(self, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.find_granule.return_value = None

        result = sync_granule('no2', self.timestamp, client=client)

        assert result is None
        assert Granule.objects.count() == 0
        client.fetch_granule_bytes.assert_not_called()

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_skips_without_fetching_when_already_up_to_date(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)
        mock_parse.return_value = make_granule_data(version='V03')

        client = MagicMock()
        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        sync_granule('no2', self.timestamp, client=client)  # first sync: creates V03
        result = sync_granule('no2', self.timestamp, client=client)  # second sync: still V03

        assert result is None
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        # The whole point of CMR-based version resolution: the second call
        # already knows from find_granule() alone that nothing has changed,
        # so it never downloads or parses anything.
        assert client.fetch_granule_bytes.call_count == 1
        assert mock_parse.call_count == 1

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_replaces_when_nasa_version_is_newer(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        mock_parse.return_value = make_granule_data(version='V03')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V04')
        mock_parse.return_value = make_granule_data(version='V04')
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert result.version == 'V04'
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        assert client.fetch_granule_bytes.call_count == 2

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_standard_replaces_nrt_regardless_of_version_numbers(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=False, version='V02')
        mock_parse.return_value = make_granule_data(version='V02')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V01')  # lower version string, but standard tier
        mock_parse.return_value = make_granule_data(version='V01')
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert result.is_final is True
        assert result.version == 'V01'

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_nrt_never_replaces_existing_standard_data(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        mock_parse.return_value = make_granule_data(version='V03')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=False, version='V99')  # even a "higher" NRT version must not win
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is None
        stored = Granule.objects.get(product='no2', timestamp=self.timestamp)
        assert stored.is_final is True
        assert stored.version == 'V03'
        assert client.fetch_granule_bytes.call_count == 1  # only the first (accepted) sync ever fetched
