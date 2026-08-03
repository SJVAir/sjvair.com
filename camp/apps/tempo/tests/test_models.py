import pytest

from django.contrib.gis.gdal import GDALRaster
from django.contrib.gis.geos import Polygon
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from camp.apps.tempo.models import Granule


def make_raster():
    return GDALRaster({
        'width': 2,
        'height': 2,
        'srid': 4326,
        'origin': [-120.0, 37.0],
        'scale': [0.02, -0.02],
        'bands': [{'data': [1.0, 2.0, 3.0, 4.0], 'nodata_value': -9999.0}],
    })


class GranuleTests(TestCase):
    def test_create_and_str(self):
        granule = Granule.objects.create(
            product=Granule.Product.NO2,
            timestamp=timezone.now(),
            version='V03',
            is_final=False,
            raster=make_raster(),
            bounds=Polygon.from_bbox((-120.0, 36.96, -119.96, 37.0)),
        )
        granule.preview.save('test.png', ContentFile(b'not-a-real-png'), save=True)

        assert granule.sqid
        assert 'Nitrogen Dioxide' in str(granule)

    def test_unique_together_product_timestamp(self):
        timestamp = timezone.now()
        Granule.objects.create(
            product=Granule.Product.NO2, timestamp=timestamp, version='V03',
            raster=make_raster(), bounds=Polygon.from_bbox((-120.0, 36.96, -119.96, 37.0)),
        )
        with pytest.raises(IntegrityError):
            Granule.objects.create(
                product=Granule.Product.NO2, timestamp=timestamp, version='V03',
                raster=make_raster(), bounds=Polygon.from_bbox((-120.0, 36.96, -119.96, 37.0)),
            )
