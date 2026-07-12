import tempfile
from pathlib import Path

import netCDF4
import numpy as np
from django.test import SimpleTestCase

from camp.apps.tempo.parsing import parse_granule


def build_fixture_netcdf(product='no2', quality_flags=None, processing_version=3, fill_positions=None) -> bytes:
    """
    Writes a tiny 2x2 netCDF file matching a real TEMPO L3 file's confirmed
    structure: root-level 1D lat/lon (ascending, south-to-north), a
    `product` group whose variables carry a leading size-1 `time`
    dimension, and a global `processing_version` integer attribute.
    Written to a real temp file (not in-memory) since disk-based writing
    is the well-established netCDF4-python path; `parse_granule` itself
    reads from bytes, matching what a real HTTP response body looks like.
    """
    var_path = {
        'no2': 'vertical_column_troposphere',
        'o3tot': 'column_amount_o3',
        'hcho': 'vertical_column',
        'cldo4': 'cloud_fraction',
    }[product]
    quality_path = {
        'no2': 'main_data_quality_flag',
        'o3tot': 'quality_flag',
        'hcho': 'main_data_quality_flag',
        'cldo4': 'quality_flag',
    }[product]

    if quality_flags is None:
        quality_flags = [[[0, 0], [0, 0]]]
    if fill_positions is None:
        fill_positions = []

    fill_value = -1e30
    values_data = [[[1.0e16, 2.0e16], [3.0e16, 4.0e16]]]  # row 0 = south (lat 36.98), row 1 = north (lat 37.0)
    for (row, col) in fill_positions:
        values_data[0][row][col] = fill_value

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'fixture.nc'
        with netCDF4.Dataset(path, mode='w') as ds:
            ds.setncattr('processing_version', processing_version)
            ds.createDimension('time', 1)
            ds.createDimension('latitude', 2)
            ds.createDimension('longitude', 2)

            lat = ds.createVariable('latitude', 'f8', ('latitude',))
            lat[:] = [36.98, 37.0]  # ascending, matching real TEMPO files
            lon = ds.createVariable('longitude', 'f8', ('longitude',))
            lon[:] = [-120.0, -119.98]

            product_group = ds.createGroup('product')
            values = product_group.createVariable(
                var_path, 'f8', ('time', 'latitude', 'longitude'), fill_value=fill_value,
            )
            values[:] = values_data
            quality = product_group.createVariable(
                quality_path, 'i4', ('time', 'latitude', 'longitude'),
            )
            quality[:] = quality_flags

        return path.read_bytes()


class ParseGranuleTests(SimpleTestCase):
    def test_parses_bounds_and_version(self):
        data = build_fixture_netcdf(product='no2', processing_version=3)

        result = parse_granule(data, 'no2')

        assert result.array.shape == (2, 2)
        assert result.lon_min == -120.0
        assert result.lon_max == -119.98
        assert result.lat_min == 36.98
        assert result.lat_max == 37.0
        assert result.version == 'V03'

    def test_formats_double_digit_processing_version(self):
        data = build_fixture_netcdf(product='no2', processing_version=4)

        result = parse_granule(data, 'no2')

        assert result.version == 'V04'

    def test_flips_array_to_north_up_orientation(self):
        # The fixture stores latitude ascending (south-to-north), matching
        # real TEMPO files, with row 0 = south = [1e16, 2e16] and row 1 =
        # north = [3e16, 4e16] as written. build_raster() (Task 3) expects
        # row 0 to be the northernmost row -- parse_granule must flip to
        # match, so the north row ends up at array[0] in the result.
        data = build_fixture_netcdf(product='no2')

        result = parse_granule(data, 'no2')

        assert result.array[0, 0] == 3.0e16  # north row
        assert result.array[1, 0] == 1.0e16  # south row

    def test_masks_flagged_pixels_as_nan(self):
        # Raw fixture position [0][1] (south row, east col) is flagged;
        # after parse_granule's north-up flip it lands at array[1][1].
        data = build_fixture_netcdf(product='no2', quality_flags=[[[0, 1], [0, 0]]])

        result = parse_granule(data, 'no2')

        assert np.isnan(result.array[1, 1])
        assert not np.isnan(result.array[0, 0])

    def test_masks_fill_value_pixels_as_nan_even_when_not_quality_flagged(self):
        # Raw fixture position [0][0] (south row, west col) becomes fill
        # value; after the north-up flip it lands at array[1][0].
        data = build_fixture_netcdf(product='no2', fill_positions=[(0, 0)])

        result = parse_granule(data, 'no2')

        assert np.isnan(result.array[1, 0])
        assert not np.isnan(result.array[0, 0])

    def test_parses_each_product(self):
        for product in ('no2', 'o3tot', 'hcho', 'cldo4'):
            data = build_fixture_netcdf(product=product)
            result = parse_granule(data, product)
            assert result.array.shape == (2, 2)
