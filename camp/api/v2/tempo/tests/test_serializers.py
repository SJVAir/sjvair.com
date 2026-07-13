from datetime import datetime, timezone as dt_timezone

import numpy as np
from django.contrib.gis.geos import Polygon
from django.test import TestCase

from camp.apps.tempo.models import Granule
from camp.apps.tempo.raster import build_raster
from camp.api.v2.tempo.serializers import GranuleSerializer


class GranuleSerializerTests(TestCase):
    def test_excludes_raster_includes_preview_url(self):
        raster = build_raster(np.array([[1.0]]), lon_min=-120, lat_min=36, lon_max=-119, lat_max=37)
        bounds = Polygon.from_bbox((-120, 36, -119, 37))
        bounds.srid = 4326
        granule = Granule.objects.create(
            product='no2',
            timestamp=datetime(2026, 7, 1, 13, tzinfo=dt_timezone.utc),
            version='V03',
            is_final=False,
            raster=raster,
            bounds=bounds,
        )

        data = GranuleSerializer(granule).serialize()

        assert 'raster' not in data
        assert data['is_final'] is False
        assert data['version'] == 'V03'
        assert data['bounds']['type'] == 'Polygon'
        assert data['preview_url'] is None  # no preview file saved in this fixture
