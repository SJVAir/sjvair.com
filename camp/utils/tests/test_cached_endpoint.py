# tests/test_monitor_list_cache.py
from urllib.parse import urlencode

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.api.v2.monitors.endpoints import MonitorList
from camp.utils.test import debug, get_response_data
from camp.utils.views import CachedEndpointMixin

monitor_list = MonitorList.as_view()


class CachedEndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _call(self, params=None):
        url = reverse('api:v2:monitors:monitor-list')
        if params:
            url = f'{url}?{urlencode(params, doseq=True)}'
        request = self.factory.get(url)
        with CaptureQueriesContext(connection) as ctx:
            response = monitor_list(request)
        return response, len(ctx)

    def test_cache_hit_vs_miss(self):
        # First call = miss (does real DB work)
        resp1, q1 = self._call()
        assert resp1.status_code == 200
        assert q1 > 0
        assert resp1['X-Cache-Status'] == 'MISS'

        # Second call = hit (should be fewer, ideally 0)
        resp2, q2 = self._call()
        assert resp2.status_code == 200
        assert q2 < q1
        assert resp2['X-Cache-Status'] == 'HIT'

    def test_cc_clears_cache(self):
        # Prime the cache
        self._call()               # miss
        _, q_hit = self._call()    # hit

        # _cc forces clear + recompute (more queries than a hit)
        resp_clear, q_clear = self._call({'_cc': 1})
        assert resp_clear.status_code == 200
        assert resp_clear['X-Cache-Status'] == 'BYPASS'
        assert q_clear > q_hit

        # Next call should be a hit again (few queries)
        resp_after, q_after = self._call()
        assert resp_after.status_code == 200
        assert resp_after['X-Cache-Status'] == 'HIT'
        assert q_after < q_clear

    def test_warm_prewarms_cache(self):
        # _warm recomputes and writes without reading cache
        resp_warm, q_warm = self._call({'_warm': 1})
        assert resp_warm.status_code == 200
        assert resp_warm['X-Cache-Status'] == 'REFRESH'
        assert q_warm > 0  # did real work

        # Immediately after, normal call should be a hit
        resp_after, q_after = self._call()
        assert resp_after.status_code == 200
        assert resp_after['X-Cache-Status'] == 'HIT'
        assert q_after < q_warm

    def test_control_params_do_not_change_cache_key(self):
        # Initial miss for foo=1
        resp1, q1 = self._call({'foo': '1'})
        assert resp1.status_code == 200
        assert resp1['X-Cache-Status'] == 'MISS'
        assert q1 >= 0

        # Subsequent hit
        resp2, q2 = self._call({'foo': 1})
        assert resp2.status_code == 200
        assert resp2['X-Cache-Status'] == 'HIT'
        assert q2 == 0

        # _warm should refresh same key
        resp3, q3 = self._call({'foo': '1', '_warm': 1})
        assert resp3.status_code == 200
        assert resp3['X-Cache-Status'] == 'REFRESH'
        assert q3 == q1

        # Confirm it hits again
        resp4, q4 = self._call({'foo': 1})
        assert resp4.status_code == 200
        assert resp4['X-Cache-Status'] == 'HIT'
        assert q4 == q2

    def test_prewarm(self):
        results = CachedEndpointMixin.prewarm_all_registered()
        assert len(results)

        for view_cls, status in results:
            assert status == 200
