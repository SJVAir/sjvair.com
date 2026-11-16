from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from django_smalluuid.models import uuid_default

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.purpleair.api import (
    PurpleAirAPI, PurpleAirAPIError, PurpleAirNotFound, PurpleAirRateLimited, purpleair_api,
)
from camp.apps.monitors.purpleair.history import estimate, iter_windows, monitors_for_window
from camp.apps.monitors.purpleair.models import PurpleAir, PurpleAirHistoryGap, PurpleAirHistoryJob
from camp.apps.monitors.purpleair.tasks import (
    import_purpleair_history_chunk, import_purpleair_history_tick,
)
from camp.utils.datetime import make_aware

WINDOW_START = datetime(2023, 1, 1, tzinfo=dt_timezone.utc)
WINDOW_END = datetime(2023, 1, 2, tzinfo=dt_timezone.utc)
OTHER_ID = str(uuid_default()())
API = 'camp.apps.monitors.purpleair.tasks.purpleair_api.get_sensor_history_window'


def _ts(*args):
    return make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


def _row(timestamp, pm25=10.0):
    row = {field: 1.0 for field in PurpleAirAPI.HISTORY_FIELDS}
    row.update({'pm2.5_atm_a': pm25, 'pm2.5_atm_b': pm25, 'time_stamp': int(timestamp.timestamp())})
    return row


def _rows(start, count, step=120):
    return [_row(start + timedelta(seconds=step * i)) for i in range(count)]


def _tail(end, count):
    ''' Rows ending at `end`, so a window isn't treated as a short response. '''
    return _rows(end - timedelta(seconds=120 * count), count)


def _pm25_raw(monitor):
    return entry_models.PM25.objects.filter(monitor=monitor, stage=entry_models.PM25.Stage.RAW)


class HistoryJobTests(TestCase):
    def test_defaults(self):
        job = PurpleAirHistoryJob.objects.create(
            cursor=WINDOW_END, range_start=WINDOW_START, range_end=WINDOW_END,
        )
        assert job.state == PurpleAirHistoryJob.State.RUNNING
        assert job.chunk_days == 28
        assert job.sqid
        assert job.requests_made == job.rows_fetched == job.raw_entries_created == job.data_points == 0


class HistoryChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.job = PurpleAirHistoryJob.objects.create(
            cursor=WINDOW_END, range_start=WINDOW_START, range_end=WINDOW_END,
            chunk_start=WINDOW_START, pending_tasks=1, batch_id=1,
        )

    def run_chunk(self, batch_id=1):
        import_purpleair_history_chunk(self.job.pk, str(self.monitor.pk), WINDOW_START, WINDOW_END, batch_id)
        self.job.refresh_from_db()

    @patch('time.sleep')
    def test_one_request_per_window_creates_raw_entries(self, sleep):
        rows = _rows(WINDOW_START, 700, step=120)[:700]
        with patch(API, return_value=rows) as api:
            self.run_chunk()
        assert api.call_count == 1
        assert _pm25_raw(self.monitor).count() == 2 * len(rows)
        assert self.job.pending_tasks == 0
        assert self.job.requests_made == 1
        assert self.job.rows_fetched == len(rows)
        assert self.job.raw_entries_created > 2 * len(rows)
        assert self.job.data_points == len(rows) * len(PurpleAirAPI.HISTORY_FIELDS)
        assert not PurpleAirHistoryGap.objects.exists()

    def test_no_per_entry_queries(self):
        rows = _rows(WINDOW_START, 300)
        with patch(API, return_value=rows):
            with CaptureQueriesContext(connection) as queries:
                self.run_chunk()
        # Dozens of queries for thousands of entries, not one per entry.
        assert len(queries) < 60

    @patch('time.sleep')
    def test_rate_limit_retries_only_this_window(self, sleep):
        rows = _tail(WINDOW_END, 5)
        with patch(API, side_effect=[PurpleAirRateLimited('slow'), PurpleAirRateLimited('slow'), rows]) as api:
            self.run_chunk()
        assert api.call_count == 3
        assert all(call.args[1:3] == (WINDOW_START, WINDOW_END) for call in api.call_args_list)
        assert [call.args[0] for call in sleep.call_args_list] == [5, 15]
        assert _pm25_raw(self.monitor).count() == 10
        assert not PurpleAirHistoryGap.objects.exists()
        assert self.job.requests_made == 3

    @patch('time.sleep')
    def test_rate_limit_exhausted_records_gap(self, sleep):
        with patch(API, side_effect=PurpleAirRateLimited('slow')) as api:
            self.run_chunk()
        assert api.call_count == 4
        gap = PurpleAirHistoryGap.objects.get()
        assert gap.reason == PurpleAirHistoryGap.Reason.ERROR
        assert self.job.pending_tasks == 0
        assert self.job.state == PurpleAirHistoryJob.State.RUNNING

    def test_not_found_records_gap_without_failing_job(self):
        with patch(API, side_effect=PurpleAirNotFound('gone')):
            self.run_chunk()
        gap = PurpleAirHistoryGap.objects.get()
        assert gap.reason == PurpleAirHistoryGap.Reason.NOT_FOUND
        assert (gap.job, gap.monitor.pk, gap.window_start) == (self.job, self.monitor.pk, WINDOW_START)
        assert self.job.pending_tasks == 0
        assert self.job.state == PurpleAirHistoryJob.State.RUNNING

    def test_other_error_records_gap(self):
        with patch(API, side_effect=PurpleAirAPIError('boom')):
            self.run_chunk()
        gap = PurpleAirHistoryGap.objects.get()
        assert gap.reason == PurpleAirHistoryGap.Reason.ERROR
        assert gap.message == 'boom'

    def test_repeating_a_failed_window_does_not_duplicate_the_gap(self):
        with patch(API, side_effect=PurpleAirAPIError('boom')):
            self.run_chunk()
            self.run_chunk(batch_id=None)
        assert PurpleAirHistoryGap.objects.count() == 1

    def test_short_response_requests_the_rest(self):
        first = _rows(WINDOW_START, 10)
        second = _rows(WINDOW_END - timedelta(minutes=10), 3)
        with patch(API, side_effect=[first, second]) as api:
            self.run_chunk()
        assert api.call_count == 2
        assert api.call_args_list[1].args[1] == datetime.fromtimestamp(first[-1]['time_stamp'] + 1, tz=dt_timezone.utc)
        assert not PurpleAirHistoryGap.objects.exists()
        assert _pm25_raw(self.monitor).count() == 2 * 13

    def test_sensor_that_stopped_early_is_not_a_gap(self):
        with patch(API, side_effect=[_rows(WINDOW_START, 10), []]) as api:
            self.run_chunk()
        assert api.call_count == 2
        assert not PurpleAirHistoryGap.objects.exists()

    def test_still_short_after_followups_records_truncated_gap(self):
        def short(*args, **kwargs):
            short.start += timedelta(minutes=10)
            return _rows(short.start, 2)
        short.start = WINDOW_START
        with patch(API, side_effect=short) as api:
            self.run_chunk()
        assert api.call_count == 4  # first request + 3 follow-ups
        assert PurpleAirHistoryGap.objects.get().reason == PurpleAirHistoryGap.Reason.TRUNCATED
        assert _pm25_raw(self.monitor).exists()  # what came back is still stored

    def test_near_duplicates_are_skipped_and_never_overwritten(self):
        near = WINDOW_START + timedelta(hours=1)
        entry_models.PM25.objects.create(
            monitor=self.monitor, timestamp=near + timedelta(seconds=30), sensor='a',
            stage=entry_models.PM25.Stage.RAW, value=Decimal('99.0'),
            position=self.monitor.position, location=self.monitor.location,
        )
        rows = [_row(near, pm25=5.0), _row(near + timedelta(hours=2), pm25=5.0)]
        with patch(API, return_value=rows):
            self.run_chunk()
        a = _pm25_raw(self.monitor).filter(sensor='a')
        assert a.count() == 2
        assert a.get(timestamp=near + timedelta(seconds=30)).value == Decimal('99.0')
        assert not a.filter(timestamp=near).exists()
        assert _pm25_raw(self.monitor).filter(sensor='b').count() == 2

    def test_rerun_is_idempotent(self):
        rows = _rows(WINDOW_START, 5)
        with patch(API, return_value=rows):
            self.run_chunk()
            self.run_chunk(batch_id=None)
        assert _pm25_raw(self.monitor).count() == 10

    def test_stale_batch_still_imports_but_does_not_touch_the_job(self):
        with patch(API, return_value=_rows(WINDOW_START, 3)):
            self.run_chunk(batch_id=999)
        assert _pm25_raw(self.monitor).count() == 6
        assert self.job.pending_tasks == 1
        assert self.job.requests_made == 0

    def test_untracked_run_updates_counters_but_not_pending(self):
        with patch(API, return_value=_tail(WINDOW_END, 3)):
            self.run_chunk(batch_id=None)
        assert self.job.pending_tasks == 1
        assert self.job.requests_made == 1
        assert self.job.rows_fetched == 3

    def test_missing_monitor_still_reports_completion(self):
        with patch(API) as api:
            import_purpleair_history_chunk(self.job.pk, OTHER_ID, WINDOW_START, WINDOW_END, 1)
        assert api.call_count == 0
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0


class MonitorsForWindowTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()

    def test_monitor_with_no_latest_entries_is_included(self):
        assert monitors_for_window(WINDOW_START, WINDOW_END) == [self.monitor.pk]

    def test_monitor_that_stopped_before_the_window_is_skipped(self):
        LatestEntry.objects.create(
            monitor=self.monitor, entry_type=entry_models.PM25.entry_type, entry_id=OTHER_ID,
            timestamp=WINDOW_START - timedelta(days=1),
        )
        assert monitors_for_window(WINDOW_START, WINDOW_END) == []
        LatestEntry.objects.update(timestamp=WINDOW_START + timedelta(days=1))
        assert monitors_for_window(WINDOW_START, WINDOW_END) == [self.monitor.pk]

    def test_monitor_ids_filter(self):
        assert monitors_for_window(WINDOW_START, WINDOW_END, [OTHER_ID]) == []

    def test_windows_walk_back_from_range_end(self):
        windows = list(iter_windows(_ts(2023, 1, 1), _ts(2023, 3, 1), 28))
        assert windows[0][1] == _ts(2023, 3, 1)
        assert windows[-1][0] == _ts(2023, 1, 1)
        assert len(windows) == 3

    def test_estimate(self):
        windows, requests, data_points = estimate(WINDOW_START, WINDOW_START + timedelta(days=2), 1)
        assert (windows, requests) == (2, 2)
        assert data_points == 2 * 720 * len(PurpleAirAPI.HISTORY_FIELDS)


class HistoryTickTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2023, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        self.job = PurpleAirHistoryJob.objects.create(
            cursor=self.range_end, range_start=self.range_start, range_end=self.range_end, chunk_days=7,
        )

    def tick(self):
        with self.captureOnCommitCallbacks(execute=True):
            import_purpleair_history_tick()
        self.job.refresh_from_db()

    def test_no_op_when_no_running_job(self):
        self.job.state = PurpleAirHistoryJob.State.DONE
        self.job.save()
        with patch(API) as api:
            self.tick()
        assert api.call_count == 0

    def test_dispatches_then_completes_the_window(self):
        with patch(API, return_value=_tail(self.range_end, 3)) as api:
            self.tick()
            assert api.call_count == 1
            assert self.job.pending_tasks == 0
            assert self.job.chunk_start == self.range_start
            self.job.locked_at = None
            self.job.save()
            self.tick()
        assert self.job.state == PurpleAirHistoryJob.State.DONE
        assert self.job.cursor == self.range_start
        assert _pm25_raw(self.monitor).count() == 6

    def test_monitor_ids_limit_the_dispatch(self):
        self.job.monitor_ids = [OTHER_ID]
        self.job.save()
        with patch(API) as api:
            self.tick()
        assert api.call_count == 0
        assert self.job.pending_tasks == 0


class HistoryTickStalenessTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.range_end = _ts(2023, 1, 8)
        self.job = PurpleAirHistoryJob.objects.create(
            cursor=self.range_end, range_start=_ts(2023, 1, 1), range_end=self.range_end, chunk_days=7,
            chunk_start=_ts(2023, 1, 1), pending_tasks=1, batch_id=1,
            phase_started_at=timezone.now() - timedelta(minutes=61),
        )

    def tick(self):
        with patch(API, side_effect=PurpleAirAPIError('x')):
            with self.captureOnCommitCallbacks(execute=True):
                import_purpleair_history_tick()
        self.job.refresh_from_db()

    def test_stale_batch_is_restarted(self):
        self.tick()
        assert self.job.batch_id == 2
        assert self.job.consecutive_failures == 1
        assert self.job.state == PurpleAirHistoryJob.State.RUNNING

    def test_slow_batch_with_recent_progress_is_left_alone(self):
        self.job.last_progress_at = timezone.now() - timedelta(minutes=5)
        self.job.save()
        self.tick()
        assert self.job.batch_id == 1
        assert self.job.consecutive_failures == 0

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ADMINS=[('Test Admin', 'admin@example.com')],
    )
    def test_repeated_staleness_fails_the_job_and_resume_redispatches(self):
        self.job.consecutive_failures = 4
        self.job.save()
        self.tick()
        assert self.job.state == PurpleAirHistoryJob.State.FAILED
        assert self.job.chunk_start is None
        assert mail.outbox[0].subject == '[SJVAir] PurpleAir history import failed'

        self.job.state = PurpleAirHistoryJob.State.RUNNING
        self.job.locked_at = None
        self.job.save()
        self.tick()
        assert self.job.cursor == self.range_end
        assert self.job.consecutive_failures == 0
        assert self.job.batch_id == 2


class HistoryCommandTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_start_creates_job_with_defaults(self):
        out = StringIO()
        call_command('import_purpleair_history', 'start', '--from', '2020-01-01', stdout=out)
        job = PurpleAirHistoryJob.objects.get()
        assert job.chunk_days == 28
        assert job.cursor == job.range_end
        assert timezone.now() - job.range_end < timedelta(hours=25)
        assert 'Started' in out.getvalue()

    def test_start_requires_from(self):
        with pytest.raises(CommandError):
            call_command('import_purpleair_history', 'start')

    def test_start_rejects_bad_ranges_and_unknown_monitors(self):
        with pytest.raises(CommandError):
            call_command('import_purpleair_history', 'start', '--from', '2020-02-01', '--to', '2020-01-01')
        with pytest.raises(CommandError):
            call_command('import_purpleair_history', 'start', '--from', '2020-01-01', '--monitor-id', OTHER_ID)
        assert not PurpleAirHistoryJob.objects.exists()

    def test_start_refuses_second_job_without_force(self):
        call_command('import_purpleair_history', 'start', '--from', '2020-01-01')
        with pytest.raises(CommandError):
            call_command('import_purpleair_history', 'start', '--from', '2020-01-01')
        call_command('import_purpleair_history', 'start', '--from', '2021-01-01', '--force')
        assert PurpleAirHistoryJob.objects.count() == 1
        assert PurpleAirHistoryJob.objects.get().range_start == _ts(2021, 1, 1)

    def test_monitor_id_is_stored(self):
        monitor = PurpleAir.objects.first()
        call_command('import_purpleair_history', 'start', '--from', '2020-01-01', '--monitor-id', str(monitor.pk))
        assert PurpleAirHistoryJob.objects.get().monitor_ids == [str(monitor.pk)]

    def test_dry_run_creates_nothing_and_reports_counts(self):
        out = StringIO()
        call_command(
            'import_purpleair_history', 'start', '--from', '2023-01-01', '--to', '2023-03-01', '--dry-run',
            stdout=out,
        )
        assert not PurpleAirHistoryJob.objects.exists()
        text = out.getvalue()
        assert 'Monitors: 1' in text
        assert 'Windows: 3' in text
        assert 'Requests: 3' in text
        assert 'Estimated data points:' in text

    def test_status_cancel(self):
        out = StringIO()
        call_command('import_purpleair_history', 'status', stdout=out)
        assert 'No import job' in out.getvalue()

        call_command('import_purpleair_history', 'start', '--from', '2020-01-01')
        out = StringIO()
        call_command('import_purpleair_history', 'status', stdout=out)
        assert 'State: running' in out.getvalue()

        call_command('import_purpleair_history', 'cancel')
        assert PurpleAirHistoryJob.objects.get().state == PurpleAirHistoryJob.State.DONE

    def test_status_lists_gaps_and_retry_reimports_them(self):
        monitor = PurpleAir.objects.first()
        job = PurpleAirHistoryJob.objects.create(
            cursor=WINDOW_START, range_start=WINDOW_START, range_end=WINDOW_END,
            state=PurpleAirHistoryJob.State.DONE,
        )
        PurpleAirHistoryGap.objects.create(
            job=job, monitor=monitor, window_start=WINDOW_START, window_end=WINDOW_END,
            reason=PurpleAirHistoryGap.Reason.ERROR, message='boom',
        )
        out = StringIO()
        call_command('import_purpleair_history', 'status', stdout=out)
        assert 'error' in out.getvalue() and 'boom' in out.getvalue()

        with patch(API, return_value=_tail(WINDOW_END, 3)):
            call_command('import_purpleair_history', 'retry')
        assert not PurpleAirHistoryGap.objects.exists()
        assert _pm25_raw(monitor).count() == 6
        job.refresh_from_db()
        assert job.pending_tasks == 0

    def test_retry_records_the_gap_again_when_it_still_fails(self):
        monitor = PurpleAir.objects.first()
        job = PurpleAirHistoryJob.objects.create(
            cursor=WINDOW_START, range_start=WINDOW_START, range_end=WINDOW_END,
        )
        PurpleAirHistoryGap.objects.create(
            job=job, monitor=monitor, window_start=WINDOW_START, window_end=WINDOW_END,
            reason=PurpleAirHistoryGap.Reason.ERROR,
        )
        with patch(API, side_effect=PurpleAirNotFound('gone')):
            call_command('import_purpleair_history', 'retry')
        assert PurpleAirHistoryGap.objects.get().reason == PurpleAirHistoryGap.Reason.NOT_FOUND

    def test_retry_with_no_gaps(self):
        out = StringIO()
        call_command('import_purpleair_history', 'retry', stdout=out)
        assert 'No gaps' in out.getvalue()


def _response(payload, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    return response


class PurpleAirAPIHistoryTests(TestCase):
    def ok(self):
        return _response({'fields': ['time_stamp', 'humidity'], 'data': [[200, 2.0], [100, 1.0]]})

    def test_window_makes_one_request_and_sorts_rows(self):
        with patch.object(purpleair_api, 'get', return_value=self.ok()) as get:
            rows = purpleair_api.get_sensor_history_window(42, WINDOW_START, WINDOW_END)
        assert get.call_count == 1
        assert [r['time_stamp'] for r in rows] == [100, 200]
        assert rows[0]['sensor_index'] == 42
        params = get.call_args.kwargs['params']
        assert params['start_timestamp'] == int(WINDOW_START.timestamp())
        assert params['average'] == 0

    def test_window_error_mapping(self):
        cases = [
            (_response({'error': 'RateLimitExceededError'}), PurpleAirRateLimited),
            (_response({'error': 'NotFoundError'}, status=404), PurpleAirNotFound),
            (_response({}, status=404), PurpleAirNotFound),
            (_response({'error': 'ApiKeyInvalidError'}, status=403), PurpleAirAPIError),
        ]
        for response, error in cases:
            with patch.object(purpleair_api, 'get', return_value=response):
                with pytest.raises(error):
                    purpleair_api.get_sensor_history_window(42, WINDOW_START, WINDOW_END)

    def test_window_wraps_network_errors(self):
        import requests
        with patch.object(purpleair_api, 'get', side_effect=requests.ConnectionError('down')):
            with pytest.raises(PurpleAirAPIError):
                purpleair_api.get_sensor_history_window(42, WINDOW_START, WINDOW_END)

    @patch('time.sleep')
    def test_get_sensor_history_rate_limit_retries_only_the_current_chunk(self, sleep):
        limited = _response({'error': 'RateLimitExceededError'})
        responses = [self.ok(), limited, self.ok()]  # chunk 1, chunk 2 (limited once), chunk 2 again
        start = datetime(2023, 1, 1)
        end = datetime(2023, 1, 28)  # two 14-day chunks
        with patch.object(purpleair_api, 'get', side_effect=responses) as get:
            rows = list(purpleair_api.get_sensor_history(42, start, end, batch_days=14))
        assert get.call_count == 3
        stamps = [c.kwargs['params']['start_timestamp'] for c in get.call_args_list]
        assert stamps[0] != stamps[1] and stamps[1] == stamps[2]  # chunk 1 was not re-fetched
        assert len(rows) == 4

    @patch('time.sleep')
    def test_get_sensor_history_gives_up_after_bounded_attempts(self, sleep):
        limited = _response({'error': 'RateLimitExceededError'})
        with patch.object(purpleair_api, 'get', return_value=limited) as get:
            rows = list(purpleair_api.get_sensor_history(42, datetime(2023, 1, 1), datetime(2023, 1, 2)))
        assert rows == []
        assert get.call_count == PurpleAirAPI.HISTORY_RATE_LIMIT_ATTEMPTS
