from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import dairies, methane, stats, warm, wells


class WarmTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def test_paths_cover_the_landing_county_tabs_and_a_facility(self):
        paths = warm.warm_paths()
        assert reverse('emissions:home') in paths
        assert any(path.endswith('/oil-gas/') and '/region/' in path for path in paths)
        assert any(path.startswith('/tools/emissions/facilities/') and path.count('/') > 5 for path in paths)

    def test_warm_renders_each_page_once_per_version(self):
        first = warm.warm()
        assert first['failed'] == 0 and first['warmed'] == len(warm.warm_paths())
        assert warm.warm()['warmed'] == 0
        # Any module's import retires the lot.
        stats.clear_caches()
        assert warm.warm()['warmed'] == first['warmed']

    def test_any_modules_bump_retires_every_modules_keys(self):
        # A dairy page reads CEIDARS facilities, a stats page reads dairies:
        # a bump anywhere has to orphan everything.
        before = (dairies.key('x'), wells.key('x'), methane.key('x'), stats.prefix())
        dairies.clear_caches()
        after = (dairies.key('x'), wells.key('x'), methane.key('x'), stats.prefix())
        assert all(old != new for old, new in zip(before, after))

    def test_clear_caches_queues_a_warm_pass_after_commit(self):
        with patch('camp.apps.emissions.tasks.warm_emissions_caches_now') as task:
            with self.captureOnCommitCallbacks(execute=True):
                stats.clear_caches()
        task.schedule.assert_called_once_with(delay=60)
