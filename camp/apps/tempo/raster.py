import numpy as np

from django.contrib.gis.gdal import GDALRaster

NODATA_VALUE = -9999.0


def build_raster(
    array: np.ndarray,
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    srid: int = 4326,
) -> GDALRaster:
    """
    Builds a single-band GDALRaster from a 2D array of column-density
    values, oriented north-up (row 0 = northernmost). NaN cells are stored
    using a sentinel nodata value, since raster bands don't support NaN
    directly for most pixel types.
    """
    height, width = array.shape
    scale_x = (lon_max - lon_min) / width
    scale_y = -(lat_max - lat_min) / height  # negative: rows run north-to-south

    data = np.where(np.isnan(array), NODATA_VALUE, array).astype(np.float64)

    return GDALRaster({
        'width': width,
        'height': height,
        'srid': srid,
        'origin': [lon_min, lat_max],
        'scale': [scale_x, scale_y],
        'bands': [{
            'data': data.flatten().tolist(),
            'nodata_value': NODATA_VALUE,
        }],
    })
