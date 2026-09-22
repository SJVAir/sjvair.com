from datetime import datetime, timedelta
from unittest import mock

import geopandas as gpd
import pytest
import requests

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .models import Fire, Smoke
from .tasks import fetch_fire, fetch_fire_final, fetch_smoke, fetch_smoke_final, import_hms_range, parse_timestamp


TEST_DATE = datetime(2025, 9, 1).date()


class ParseTimestampTests(TestCase):
    def test_julian_date_format(self):
        result = parse_timestamp('2025244 0600')
        assert result.year == 2025
        assert result.month == 9
        assert result.day == 1
        assert result.hour == 6
        assert result.minute == 0
        assert result.tzinfo is not None


class FetchSmokeTests(TestCase):
    fixtures = ['regions.yaml']

    def test_fetch_smoke(self):
        assert Smoke.objects.count() == 0
        fetch_smoke.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() > 0

    def test_fetch_smoke_sets_fields(self):
        fetch_smoke.call_local(TEST_DATE)
        smoke = Smoke.objects.filter(date=TEST_DATE).first()
        assert smoke.satellite
        assert smoke.density in ('light', 'medium', 'heavy')
        assert smoke.start is not None
        assert smoke.end is not None
        assert smoke.geometry is not None

    def test_fetch_smoke_replaces_existing(self):
        fetch_smoke.call_local(TEST_DATE)
        count = Smoke.objects.filter(date=TEST_DATE).count()
        assert count > 0
        fetch_smoke.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() == count

    def test_fetch_smoke_final(self):
        fetch_smoke_final.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() > 0


class FetchFireTests(TestCase):
    fixtures = ['regions.yaml']

    def test_fetch_fire(self):
        assert Fire.objects.count() == 0
        fetch_fire.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() > 0

    def test_fetch_fire_sets_fields(self):
        fetch_fire.call_local(TEST_DATE)
        fire = Fire.objects.filter(date=TEST_DATE).first()
        assert fire.satellite
        assert fire.timestamp is not None
        assert fire.frp is not None
        assert fire.ecosystem is not None
        assert fire.method
        assert fire.geometry is not None

    def test_fetch_fire_replaces_existing(self):
        fetch_fire.call_local(TEST_DATE)
        count = Fire.objects.filter(date=TEST_DATE).count()
        assert count > 0
        fetch_fire.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() == count

    def test_fetch_fire_final(self):
        fetch_fire_final.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() > 0


class FetchKwargsTests(TestCase):
    '''
    HMS files are revised under the same URL throughout the day, so the
    tasks must bypass the geodata download cache. Smoke plumes are large
    regional polygons, so any plume touching the region must be kept.
    '''

    fixtures = ['regions.yaml']

    @mock.patch('camp.apps.hms.tasks.geodata.gdf_from_url', return_value=gpd.GeoDataFrame())
    def test_fetch_smoke_keeps_any_intersecting_plume_and_skips_cache(self, gdf_from_url):
        fetch_smoke.call_local(TEST_DATE)
        kwargs = gdf_from_url.call_args.kwargs
        assert kwargs['limit_to_region'] is True
        assert kwargs['threshold'] == 0.0
        assert kwargs['cache'] is False

    @mock.patch('camp.apps.hms.tasks.geodata.gdf_from_url', return_value=gpd.GeoDataFrame())
    def test_fetch_fire_skips_cache(self, gdf_from_url):
        fetch_fire.call_local(TEST_DATE)
        kwargs = gdf_from_url.call_args.kwargs
        assert kwargs['limit_to_region'] is True
        assert kwargs['cache'] is False


class ImportHmsRangeTests(TestCase):
    start = datetime(2026, 9, 1).date()
    end = datetime(2026, 9, 3).date()

    def setUp(self):
        self.sleep = mock.patch('camp.apps.hms.tasks.time.sleep').start()
        self.smoke = mock.patch('camp.apps.hms.tasks.fetch_smoke').start()
        self.fire = mock.patch('camp.apps.hms.tasks.fetch_fire').start()
        self.addCleanup(mock.patch.stopall)

    def dates(self, task):
        return [call.args[0] for call in task.call_local.call_args_list]

    def test_runs_both_in_date_order(self):
        import_hms_range.call_local(self.start, self.end)
        expected = [self.start, self.start + timedelta(days=1), self.end]
        assert self.dates(self.smoke) == expected
        assert self.dates(self.fire) == expected

    def test_smoke_only(self):
        import_hms_range.call_local(self.start, self.end, fire=False)
        assert len(self.dates(self.smoke)) == 3
        assert self.dates(self.fire) == []

    def test_sleeps_between_downloads_but_not_after_last(self):
        import_hms_range.call_local(self.start, self.end, delay=1.5)
        assert self.sleep.call_count == 5
        assert all(c.args == (1.5,) for c in self.sleep.call_args_list)

    def test_reversed_range_is_normalized(self):
        import_hms_range.call_local(self.end, self.start, fire=False)
        assert self.dates(self.smoke) == [self.start, self.start + timedelta(days=1), self.end]

    def test_missing_file_is_skipped(self):
        response = mock.Mock(status_code=404)
        self.smoke.call_local.side_effect = [None, requests.HTTPError(response=response), None]
        result = import_hms_range.call_local(self.start, self.end, fire=False)
        assert len(self.dates(self.smoke)) == 3
        assert result['skipped'] == [f'smoke {self.start + timedelta(days=1)}']

    def test_other_errors_propagate(self):
        response = mock.Mock(status_code=500)
        self.smoke.call_local.side_effect = requests.HTTPError(response=response)
        with pytest.raises(requests.HTTPError):
            import_hms_range.call_local(self.start, self.end, fire=False)


class ImportHmsCommandTests(TestCase):
    @mock.patch('camp.apps.hms.management.commands.import_hms.import_hms_range')
    def test_range_runs_inline_by_default(self, task):
        call_command('import_hms', '--start', '2026-09-01', '--end', '2026-09-03', '--delay', '5')
        task.call_local.assert_called_once_with(
            datetime(2026, 9, 1).date(), datetime(2026, 9, 3).date(), smoke=True, fire=True, delay=5.0,
        )
        task.assert_not_called()

    @mock.patch('camp.apps.hms.management.commands.import_hms.import_hms_range')
    def test_range_can_be_queued(self, task):
        call_command('import_hms', '--start', '2026-09-01', '--end', '2026-09-03', '--fire', '--queue')
        task.assert_called_once_with(
            datetime(2026, 9, 1).date(), datetime(2026, 9, 3).date(), smoke=False, fire=True, delay=0.5,
        )
        task.call_local.assert_not_called()

    @mock.patch('camp.apps.hms.management.commands.import_hms.fetch_fire')
    @mock.patch('camp.apps.hms.management.commands.import_hms.fetch_smoke')
    def test_single_date_still_works(self, smoke, fire):
        call_command('import_hms', '2026-09-01')
        smoke.call_local.assert_called_once_with(datetime(2026, 9, 1).date())
        fire.call_local.assert_called_once_with(datetime(2026, 9, 1).date())

    def test_start_without_end_is_rejected(self):
        with pytest.raises(CommandError):
            call_command('import_hms', '--start', '2026-09-01')
