from unittest import mock

import geopandas as gpd
from django.test import SimpleTestCase
from shapely.geometry import box

from camp.utils import geodata


class FilterByOverlapTests(SimpleTestCase):
    def setUp(self):
        self.region = box(0, 0, 10, 10)
        # A large polygon that only barely overlaps the region (1% of its own area).
        self.plume = box(9, 9, 19, 19)

    def rows(self):
        return iter(gpd.GeoDataFrame({'name': ['plume']}, geometry=[self.plume]).iloc[[0]].pipe(lambda g: [g.iloc[0]]))

    def test_default_threshold_drops_mostly_outside_polygon(self):
        result = list(geodata.filter_by_overlap(self.rows(), self.region))
        assert result == []

    def test_zero_threshold_keeps_any_intersecting_polygon(self):
        result = list(geodata.filter_by_overlap(self.rows(), self.region, threshold=0.0))
        assert len(result) == 1

    def test_zero_threshold_still_drops_non_intersecting_polygon(self):
        self.plume = box(20, 20, 30, 30)
        result = list(geodata.filter_by_overlap(self.rows(), self.region, threshold=0.0))
        assert result == []


class IterFromUrlCacheTests(SimpleTestCase):
    url = 'https://example.com/data.zip'

    def cache_path(self):
        return geodata.GEODATA_CACHE_DIR / f'{geodata.cache_key(self.url)}.zip'

    def setUp(self):
        self.cache_path().write_bytes(b'stale')
        self.addCleanup(lambda: self.cache_path().unlink(missing_ok=True))

    @mock.patch('camp.utils.geodata.iter_from_zip', return_value=iter([]))
    @mock.patch('camp.utils.geodata.stream_to_disk')
    def test_cached_file_is_reused_by_default(self, stream_to_disk, iter_from_zip):
        geodata.iter_from_url(self.url)
        stream_to_disk.assert_not_called()
        iter_from_zip.assert_called_once()

    @mock.patch('camp.utils.geodata.iter_from_zip', return_value=iter([]))
    @mock.patch('camp.utils.geodata.stream_to_disk')
    def test_cache_false_redownloads_over_existing_file(self, stream_to_disk, iter_from_zip):
        geodata.iter_from_url(self.url, cache=False)
        stream_to_disk.assert_called_once()
        assert stream_to_disk.call_args.kwargs['dest'] == self.cache_path()
        iter_from_zip.assert_called_once()
