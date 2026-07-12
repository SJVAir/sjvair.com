import numpy as np
from django.contrib.gis.gdal import GDALRaster

from camp.apps.tempo.raster import build_raster


def test_build_raster_dimensions_and_srid():
    array = np.array([[1.0, 2.0], [3.0, 4.0]])
    raster = build_raster(array, lon_min=-120.0, lat_min=36.96, lon_max=-119.96, lat_max=37.0)

    assert isinstance(raster, GDALRaster)
    assert raster.width == 2
    assert raster.height == 2
    assert raster.srs.srid == 4326


def test_build_raster_preserves_values():
    array = np.array([[1.0, 2.0], [3.0, 4.0]])
    raster = build_raster(array, lon_min=-120.0, lat_min=36.96, lon_max=-119.96, lat_max=37.0)

    band_data = raster.bands[0].data()
    assert list(band_data.flatten()) == [1.0, 2.0, 3.0, 4.0]


def test_build_raster_maps_nan_to_nodata():
    array = np.array([[1.0, np.nan]])
    raster = build_raster(array, lon_min=-120.0, lat_min=36.98, lon_max=-119.96, lat_max=37.0)

    assert raster.bands[0].nodata_value == -9999.0
    band_data = raster.bands[0].data()
    assert band_data.flatten()[1] == -9999.0
