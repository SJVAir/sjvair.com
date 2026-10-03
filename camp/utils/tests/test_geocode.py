from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.test import SimpleTestCase

from camp.utils.geocode import clean_address, maptiler


class TestCleanAddress(SimpleTestCase):
    def test_strips_unit_suffix(self):
        assert clean_address('123 MAIN ST #4') == '123 MAIN ST'

    def test_strips_apt_suffix(self):
        assert clean_address('123 MAIN ST APT 2B') == '123 MAIN ST'

    def test_strips_suite_suffix(self):
        assert clean_address('123 MAIN ST SUITE 100') == '123 MAIN ST'

    def test_preserves_normal_address(self):
        assert clean_address('123 MAIN ST') == '123 MAIN ST'

    def test_handles_non_string(self):
        assert clean_address(None) == ''

    def test_normalizes_whitespace(self):
        assert clean_address('  123 MAIN ST  ') == '123 MAIN ST'


def _maptiler_response(*place_types_list):
    """Build a fake MapTiler response with one feature per entry in place_types_list."""
    features = []
    for place_types in place_types_list:
        features.append({
            'place_type': place_types,
            'geometry': {'coordinates': [-119.787, 36.737]},
        })
    mock = MagicMock()
    mock.json.return_value = {'features': features}
    mock.raise_for_status.return_value = None
    return mock


class TestMaptilerGeocoder(SimpleTestCase):
    def test_returns_first_address_feature(self):
        with patch('requests.get', return_value=_maptiler_response(['address'])):
            result = maptiler('123 Main St, Fresno, CA')
        assert result == Point(-119.787, 36.737, srid=4326)

    def test_returns_first_poi_feature(self):
        with patch('requests.get', return_value=_maptiler_response(['poi'])):
            result = maptiler('123 Main St, Fresno, CA')
        assert result == Point(-119.787, 36.737, srid=4326)

    def test_skips_low_precision_types(self):
        with patch('requests.get', return_value=_maptiler_response(['municipality'])):
            result = maptiler('123 Main St, Fresno, CA')
        assert result is None

    def test_returns_address_before_poi_when_address_first(self):
        # address appears first — should be returned
        with patch('requests.get', return_value=_maptiler_response(['address'], ['poi'])):
            result = maptiler('123 Main St, Fresno, CA')
        assert result == Point(-119.787, 36.737, srid=4326)

    def test_strict_skips_poi(self):
        with patch('requests.get', return_value=_maptiler_response(['poi'])):
            result = maptiler('123 Main St, Fresno, CA', strict=True)
        assert result is None

    def test_strict_returns_address(self):
        with patch('requests.get', return_value=_maptiler_response(['address'])):
            result = maptiler('123 Main St, Fresno, CA', strict=True)
        assert result == Point(-119.787, 36.737, srid=4326)

    def test_strict_finds_address_after_poi(self):
        # poi comes first, address comes second — strict mode should skip poi and return address
        with patch('requests.get', return_value=_maptiler_response(['poi'], ['address'])):
            result = maptiler('123 Main St, Fresno, CA', strict=True)
        assert result == Point(-119.787, 36.737, srid=4326)

    def test_strict_returns_none_when_only_low_precision(self):
        with patch('requests.get', return_value=_maptiler_response(['municipality'], ['postal_code'])):
            result = maptiler('123 Main St, Fresno, CA', strict=True)
        assert result is None
