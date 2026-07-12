from dataclasses import dataclass

import netCDF4
import numpy as np

# Variable paths within each TEMPO L3 product's `product` group. no2's
# entries are confirmed against a real downloaded granule (2026-07-11);
# o3tot/hcho/cldo4 follow the same shared L3 pipeline's naming convention
# but were not individually verified -- see this task's notes above.
PRODUCT_VARIABLE_PATHS = {
    'no2': 'vertical_column_troposphere',
    'o3tot': 'column_amount_o3',
    'hcho': 'vertical_column',
    'cldo4': 'cloud_fraction',
}

QUALITY_FLAG_PATHS = {
    'no2': 'main_data_quality_flag',
    'o3tot': 'quality_flag',
    'hcho': 'main_data_quality_flag',
    'cldo4': 'quality_flag',
}


@dataclass
class GranuleData:
    array: np.ndarray
    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float
    version: str


def parse_granule(data: bytes, product: str) -> GranuleData:
    """
    Parses a subsetted TEMPO L3 netCDF file into a GranuleData. Pixels
    flagged by the product's quality variable (any value other than 0,
    "normal") or equal to the variable's own _FillValue are set to NaN.
    The returned array is always north-up (row 0 = northernmost row),
    regardless of how the source file stores latitude.
    """
    with netCDF4.Dataset('in-memory-granule', mode='r', memory=data) as ds:
        product_group = ds.groups['product']
        values_var = product_group[PRODUCT_VARIABLE_PATHS[product]]
        values = np.array(values_var[:], dtype=np.float64)
        fill_value = values_var.getncattr('_FillValue') if '_FillValue' in values_var.ncattrs() else None

        quality = np.array(product_group[QUALITY_FLAG_PATHS[product]][:])

        # lat/lon are 1D coordinate variables at the file's root, not
        # inside a subgroup.
        lat = np.array(ds.variables['latitude'][:])
        lon = np.array(ds.variables['longitude'][:])

        version_number = int(ds.getncattr('processing_version')) if 'processing_version' in ds.ncattrs() else None
        version = f'V{version_number:02d}' if version_number is not None else 'UNKNOWN'

    # Main variable and quality flag carry a leading size-1 `time`
    # dimension (each TEMPO L3 file covers exactly one hour) -- drop it.
    if values.ndim == 3:
        values = values[0]
    if quality.ndim == 3:
        quality = quality[0]

    # Raw TEMPO files store latitude ascending (south-to-north); flip so
    # row 0 is the northernmost row, matching build_raster()'s north-up
    # (negative scale_y) convention.
    if lat[0] < lat[-1]:
        values = np.flipud(values)
        quality = np.flipud(quality)

    mask = quality != 0
    if fill_value is not None:
        mask = mask | (values == fill_value)
    values = np.where(mask, np.nan, values)

    return GranuleData(
        array=values,
        lon_min=float(lon.min()),
        lat_min=float(lat.min()),
        lon_max=float(lon.max()),
        lat_max=float(lat.max()),
        version=version,
    )
