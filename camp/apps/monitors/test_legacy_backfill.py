from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, PM_COLUMN_CUTOVER, build_raw_entry, chunk_start_for, find_missing_raw_entries,
    monitors_with_legacy_data_in, find_incomplete_pipelines, monitors_with_incomplete_pipelines_in,
    pipeline_entry_models,
)
from camp.apps.monitors.models import Entry, EntryBackfillJob, PipelineBackfillJob
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware


def _legacy_entry(monitor, **kwargs):
    defaults = {
        'monitor': monitor,
        'sensor': '',
        'location': Entry._meta.get_field('location').choices[0][0],
    }
    defaults.update(kwargs)
    return Entry(**defaults)


class BuildRawEntryPurpleAirTests(TestCase):
    def setUp(self):
        self.monitor = PurpleAir(name='Test PurpleAir', sensor_id=1, location='outside')

    def test_pm25_uses_reported_only_not_calibrated(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=Decimal('9.50'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('9.50')
        assert entry.sensor == 'a'

    def test_pm25_returns_none_when_reported_missing(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_particulates_copies_all_fields_directly(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=Decimal('2.2'),
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping)
        assert entry.particles_03um == Decimal('1.1')
        assert entry.particles_100um == Decimal('6.6')
        assert entry.sensor == 'b'

    def test_particulates_returns_none_when_any_field_missing(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=None,
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        assert build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping) is None

    def test_temperature_and_humidity_and_pressure_collapse_sensor_to_blank(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', fahrenheit=Decimal('70.5'),
            humidity=Decimal('40.0'), pressure=Decimal('1013.25'),
        )
        temp = build_raw_entry(
            self.monitor, legacy, entry_models.Temperature,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Temperature],
        )
        humidity = build_raw_entry(
            self.monitor, legacy, entry_models.Humidity,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity],
        )
        assert temp.sensor == ''
        assert temp.fahrenheit == Decimal('70.5')
        assert humidity.sensor == ''
        assert humidity.value == Decimal('40.0')

    def test_pressure_hpa_converted_to_mmhg(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pressure=Decimal('1013.25'))
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Pressure]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Pressure, mapping)
        # 1013.25 hPa -> mmHg via the model's own hpa setter (1 hPa = 1/1.33322 mmHg)
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert entry.value == expected

    def test_per_sensor_row_with_unknown_sensor_is_skipped(self):
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        legacy = _legacy_entry(self.monitor, sensor='', pm25_reported=Decimal('5.0'))
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_shared_field_from_any_sensor_row_is_still_copied(self):
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity]
        legacy = _legacy_entry(self.monitor, sensor='', humidity=Decimal('40.0'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.Humidity, mapping)
        assert entry.value == Decimal('40.0')

    def test_raw_entry_uses_legacy_position_and_location(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25_reported=Decimal('5.0'), location='inside')
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.location == 'inside'
        assert entry.stage == entry_models.PM25.Stage.RAW
        assert entry.processor == ''


def _ts(*args):
    return make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_by_chunk_days(self):
        cursor = _ts(2023, 7, 15)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _ts(2020, 1, 4)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == range_start


class FindMissingRawEntriesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.window_start = _ts(2023, 1, 1)
        self.window_end = _ts(2023, 1, 8)

    def test_finds_legacy_row_with_no_new_entry(self):
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.window_start + timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].value == Decimal('5.0')

    def test_skips_legacy_row_that_already_has_a_new_entry(self):
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts,
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert missing == []

    def test_skips_legacy_row_with_a_new_entry_within_60_seconds(self):
        # History import stamps aligned times; legacy used last_seen.
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts + timedelta(seconds=45),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert missing == []

    def test_near_entry_across_the_window_edge_counts(self):
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.window_start + timedelta(seconds=20),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.window_start - timedelta(seconds=20),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert missing == []

    def test_copies_legacy_row_more_than_60_seconds_from_any_new_entry(self):
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts + timedelta(seconds=90),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert [e.timestamp for e in missing] == [ts + timedelta(seconds=90)]

    def test_near_entry_for_another_sensor_does_not_count(self):
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='b', timestamp=ts + timedelta(seconds=30),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert [e.sensor for e in missing] == ['b']

    def test_detects_interior_gap_not_just_head_or_tail(self):
        # Three legacy rows; only the middle one is missing its new-entry counterpart.
        timestamps = [self.window_start + timedelta(hours=h) for h in (1, 2, 3)]
        for i, ts in enumerate(timestamps):
            Entry.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts,
                location=self.monitor.location, pm25_reported=Decimal(f'{i}.0'),
            )
        for i, ts in enumerate(timestamps):
            if i == 1:
                continue  # leave the middle one un-migrated
            entry_models.PM25.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
                stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal(f'{i}.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].timestamp == timestamps[1]

    def test_per_sensor_false_dedups_across_a_and_b_rows(self):
        ts = self.window_start + timedelta(hours=1)
        for sensor in ('a', 'b'):
            Entry.objects.create(
                monitor=self.monitor, sensor=sensor, timestamp=ts,
                location=self.monitor.location, humidity=Decimal('40.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.Humidity, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].sensor == ''


class MonitorsWithLegacyDataInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_finds_monitor_with_legacy_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=monitor, sensor='a', timestamp=window_start + timedelta(hours=1),
            location=monitor.location, pm25_reported=Decimal('5.0'),
        )
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk in ids

    def test_excludes_monitor_with_no_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk not in ids

    def test_backfill_map_is_purpleair_only(self):
        assert set(LEGACY_BACKFILL_MAP) == {PurpleAir}

    def test_ignores_legacy_data_on_non_purpleair_monitor(self):
        monitor = AirNow.objects.create(name='Test AirNow', location='outside')
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=monitor, sensor='', timestamp=window_start + timedelta(hours=1),
            location=monitor.location, pm25_reported=Decimal('5.0'),
        )
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk not in ids


class EntryBackfillJobTests(TestCase):
    def test_defaults(self):
        job = EntryBackfillJob.objects.create(
            cursor=_ts(2023, 1, 8), range_start=_ts(2020, 1, 1), range_end=_ts(2023, 1, 8),
        )
        assert job.state == EntryBackfillJob.State.RUNNING
        assert job.chunk_days == 1
        assert job.pending_tasks == 0
        assert job.batch_id == 0
        assert job.raw_entries_created == 0
        assert job.sqid


class PipelineBackfillJobTests(TestCase):
    def test_defaults(self):
        job = PipelineBackfillJob.objects.create(
            cursor=_ts(2023, 1, 8), range_start=_ts(2020, 1, 1), range_end=_ts(2023, 1, 8),
        )
        assert job.state == PipelineBackfillJob.State.RUNNING
        assert job.chunk_days == 1
        assert job.entries_processed == 0
        assert job.sqid


class BackfillMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.chunk_start = _ts(2023, 1, 1)
        self.chunk_end = _ts(2023, 1, 8)
        self.job = EntryBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=_ts(2020, 1, 1), range_end=self.chunk_end,
            chunk_start=self.chunk_start, pending_tasks=1, batch_id=1,
        )
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.chunk_start + timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )

    def test_creates_raw_entries_and_decrements_pending_tasks(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert self.job.raw_entries_created == 1

    def test_stale_batch_id_still_creates_entries_but_does_not_decrement(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_idempotent_rerun_does_not_duplicate(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        self.job.batch_id = 2
        self.job.pending_tasks = 1
        self.job.save()
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 2)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).count() == 1



class BackfillMonitorChunkResilienceTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.chunk_start = _ts(2023, 1, 1)
        self.chunk_end = _ts(2023, 1, 8)
        self.job = EntryBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=_ts(2020, 1, 1), range_end=self.chunk_end,
            chunk_start=self.chunk_start, pending_tasks=1, batch_id=1,
        )

    def test_value_too_large_for_new_field_is_skipped_not_fatal(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        # Legacy pm10 allows 8 digits; the new PM10 value field tops out at 9999.99.
        for hour, pm10 in ((1, '123456.00'), (2, '7.00')):
            Entry.objects.create(
                monitor=self.monitor, sensor='a', timestamp=self.chunk_start + timedelta(hours=hour),
                location=self.monitor.location, pm10=Decimal(pm10),
            )
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        values = list(entry_models.PM10.objects.filter(monitor=self.monitor).values_list('value', flat=True))
        assert values == [Decimal('7.00')]
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert self.job.last_progress_at is not None

    def test_missing_monitor_still_reports_completion(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        from smalluuid import SmallUUID
        deleted_id = str(SmallUUID())  # valid id, no such monitor
        backfill_monitor_chunk(self.job.pk, deleted_id, self.chunk_start, self.chunk_end, 1)
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0


from camp.apps.monitors.tasks import backfill_legacy_entries_tick


class BackfillLegacyEntriesTickDispatchTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2020, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.range_end - timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        self.job = EntryBackfillJob.objects.create(
            cursor=self.range_end, range_start=self.range_start, range_end=self.range_end, chunk_days=7,
        )

    def test_dispatches_a_chunk_and_creates_entries_synchronously(self):
        # Huey runs in immediate mode under camp.settings.test, so the fanned-out
        # backfill_monitor_chunk call executes inline once the on_commit hooks
        # fire. TestCase wraps each test in a savepoint that never really
        # commits, so on_commit callbacks are captured, not run, unless
        # explicitly flushed here (mirrors BackfillSummariesTickDispatchMonitorsTests).
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0  # drained immediately (immediate-mode Huey)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()

    def test_no_op_when_no_running_job(self):
        self.job.state = EntryBackfillJob.State.DONE
        self.job.save()
        backfill_legacy_entries_tick()  # should not raise

    def test_advances_cursor_and_marks_done_when_range_exhausted(self):
        self.job.range_start = self.range_end - timedelta(days=1)
        self.job.cursor = self.range_end
        self.job.chunk_days = 7
        self.job.save()
        # First tick dispatches the (single, clamped) chunk and, once the
        # on_commit hooks are flushed, drains it immediately. A second tick
        # then notices pending_tasks == 0 and finalizes the chunk. In
        # production the two ticks are ~60s apart (crontab(minute='*')),
        # well past ENTRY_BACKFILL_LOCK_STALE_SECONDS, so the job's own
        # locked_at from the first tick never blocks the second. Here the
        # two calls happen within the same test in well under 30s, so we
        # clear locked_at between calls to simulate that real spacing
        # (mirrors how BackfillSummariesTickClaimingTests.test_skips_job_with_recent_lock
        # proves this same lock is intentionally sticky within the window).
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        EntryBackfillJob.objects.filter(pk=self.job.pk).update(locked_at=None)
        backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.state == EntryBackfillJob.State.DONE


class BackfillLegacyEntriesTickStalenessTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2020, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        self.job = EntryBackfillJob.objects.create(
            cursor=self.range_end, range_start=self.range_start, range_end=self.range_end,
            chunk_start=self.range_end - timedelta(days=7), pending_tasks=1, batch_id=1,
            phase_started_at=timezone.now() - timedelta(minutes=61),
        )

    def test_stale_batch_is_restarted(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.batch_id != 1
        assert self.job.consecutive_failures == 1
        assert self.job.state == EntryBackfillJob.State.RUNNING

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ADMINS=[('Test Admin', 'admin@example.com')],
    )
    def test_repeated_staleness_eventually_marks_job_failed(self):
        self.job.consecutive_failures = 4  # one below the threshold of 5
        self.job.save()
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.state == EntryBackfillJob.State.FAILED
        assert self.job.pending_tasks == 0

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == '[SJVAir] Legacy entries backfill failed'
        assert list(mail.outbox[0].to) == ['admin@example.com']



    def test_slow_batch_with_recent_progress_is_not_restarted(self):
        self.job.last_progress_at = timezone.now() - timedelta(minutes=5)
        self.job.save()
        backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.batch_id == 1
        assert self.job.consecutive_failures == 0

    def test_failed_job_clears_chunk_and_resumes_from_cursor(self):
        self.job.consecutive_failures = 4
        self.job.save()
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.state == EntryBackfillJob.State.FAILED
        assert self.job.chunk_start is None

        # An operator flips it back to RUNNING in the admin.
        self.job.state = EntryBackfillJob.State.RUNNING
        self.job.locked_at = None
        self.job.save()
        with self.captureOnCommitCallbacks(execute=True):
            backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.cursor == self.range_end  # the unfinished chunk wasn't skipped
        assert self.job.consecutive_failures == 0

    def test_mail_error_does_not_roll_back_failed_state(self):
        from unittest.mock import patch
        import pytest

        self.job.consecutive_failures = 4
        self.job.save()
        with patch('camp.apps.monitors.tasks.mail_admins', side_effect=OSError('smtp down')):
            with pytest.raises(OSError):
                with self.captureOnCommitCallbacks(execute=True):
                    backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.state == EntryBackfillJob.State.FAILED


from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError


class BackfillLegacyEntriesCommandTests(TestCase):
    def test_start_creates_job(self):
        out = StringIO()
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01', stdout=out)
        assert EntryBackfillJob.objects.filter(state=EntryBackfillJob.State.RUNNING).exists()
        assert 'Started' in out.getvalue()

    def test_start_refuses_second_job_without_force(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        try:
            call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert EntryBackfillJob.objects.count() == 1

    def test_start_with_force_replaces_job(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        call_command('backfill_legacy_entries', 'start', '--from', '2021-01-01', '--force')
        assert EntryBackfillJob.objects.count() == 1
        job = EntryBackfillJob.objects.first()
        assert job.range_start.year == 2021

    def test_status_with_no_job(self):
        out = StringIO()
        call_command('backfill_legacy_entries', 'status', stdout=out)
        assert 'No backfill job' in out.getvalue()

    def test_status_with_job(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        out = StringIO()
        call_command('backfill_legacy_entries', 'status', stdout=out)
        assert 'running' in out.getvalue()

    def test_cancel_sets_state_done(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        call_command('backfill_legacy_entries', 'cancel')
        job = EntryBackfillJob.objects.first()
        assert job.state == EntryBackfillJob.State.DONE

    def test_start_raises_command_error_on_invalid_date_values(self):
        try:
            call_command('backfill_legacy_entries', 'start', '--from', '2020-13-40')
            assert False, 'expected CommandError'
        except CommandError:
            pass

    def test_force_does_not_delete_existing_job_when_new_dates_invalid(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        try:
            call_command('backfill_legacy_entries', 'start', '--from', '2020-13-40', '--force')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert EntryBackfillJob.objects.count() == 1
        job = EntryBackfillJob.objects.first()
        assert job.range_start.year == 2020 and job.range_start.month == 1 and job.range_start.day == 1


class PipelineEntryModelsTests(TestCase):
    def test_purpleair_pm25_has_calibrated_terminal_stage(self):
        models_map = pipeline_entry_models(PurpleAir)
        assert models_map[entry_models.PM25] == entry_models.PM25.Stage.CALIBRATED

    def test_purpleair_pm10_excluded_no_processors(self):
        models_map = pipeline_entry_models(PurpleAir)
        assert entry_models.PM10 not in models_map

    def test_non_backfill_type_has_no_pipeline_models(self):
        assert pipeline_entry_models(AirNow) == {}


class FindIncompletePipelinesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)

    def test_finds_raw_entry_with_no_derived_entries(self):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1),
        )
        assert [e.pk for e in incomplete] == [raw.pk]

    def test_returns_entries_oldest_first(self):
        # The cleaning step needs the previous CORRECTED entry, so the pipeline
        # must see RAW entries in chronological order.
        later = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts + timedelta(minutes=2),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('5.0'),
        )
        earlier = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1),
        )
        assert [e.pk for e in incomplete] == [earlier.pk, later.pk]

    def test_skips_raw_entry_that_already_has_a_derived_entry(self):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CALIBRATED, processor='SomeCalibrator', value=Decimal('5.0'),
            origin=raw,
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1),
        )
        assert incomplete == []

    def test_continues_from_intermediate_stage_with_no_derived_entries(self):
        # PurpleAir PM2.5 migrated with CORRECTED and CLEANED but never CALIBRATED:
        # the CLEANED entry is picked up so calibration can run on it.
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        corrected = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CORRECTED, processor='PM25_LCS_Correction',
            value=Decimal('5.0'), origin=raw,
        )
        cleaned = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CLEANED, processor='PM25_LCS_Cleaning',
            value=Decimal('5.0'), origin=corrected,
        )
        incomplete = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1))
        assert [e.pk for e in incomplete] == [cleaned.pk]

    def test_terminal_stage_entries_are_never_picked_up(self):
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CALIBRATED, processor='PM25_UnivariateLinearRegression',
            value=Decimal('5.0'),
        )
        incomplete = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1))
        assert incomplete == []

    def test_orders_by_timestamp_then_stage(self):
        corrected = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CORRECTED, processor='PM25_LCS_Correction', value=Decimal('5.0'),
        )
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        later_raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts + timedelta(minutes=2),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('5.0'),
        )
        incomplete = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1))
        assert [e.pk for e in incomplete] == [raw.pk, corrected.pk, later_raw.pk]

    def test_purpleair_pm25_sensor_b_with_no_derived_entries_is_flagged_but_a_with_merged_child_is_not(self):
        '''
        Sensor 'a' produces a merged sensor='' CORRECTED child (real PM25_LCS_Correction
        behavior) -- that RAW entry should be considered handled. Sensor 'b' legitimately
        never produces a derived entry (it defers to 'a') -- with no test-created derived
        entry, it's correctly flagged as still needing a pipeline attempt.
        '''
        raw_a = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        raw_b = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='b', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.2'),
        )
        corrected = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CORRECTED, processor='PM25_LCS_Correction',
            value=Decimal('5.1'), origin=raw_a,
        )
        incomplete = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.ts, self.ts + timedelta(hours=1))
        # The merged CORRECTED entry hasn't been cleaned yet, so it's picked up too.
        assert [e.pk for e in incomplete] == [raw_b.pk, corrected.pk]


class MonitorsWithIncompletePipelinesInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_finds_monitor_with_incomplete_pipeline(self):
        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        ids = monitors_with_incomplete_pipelines_in(ts, ts + timedelta(hours=1))
        assert monitor.pk in ids

    def test_excludes_fully_processed_monitor(self):
        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        raw = entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.CALIBRATED, processor='SomeCalibrator',
            value=Decimal('5.0'), origin=raw,
        )
        ids = monitors_with_incomplete_pipelines_in(ts, ts + timedelta(hours=1))
        assert monitor.pk not in ids


    def test_finds_monitor_with_uncalibrated_cleaned_entry(self):
        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.CLEANED, processor='PM25_LCS_Cleaning', value=Decimal('5.0'),
        )
        ids = monitors_with_incomplete_pipelines_in(ts, ts + timedelta(hours=1))
        assert monitor.pk in ids

from camp.apps.monitors.tasks import reprocess_monitor_chunk


class ReprocessMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)
        self.chunk_start = self.ts
        self.chunk_end = self.ts + timedelta(hours=1)
        self.raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.0'),
        )
        self.job = PipelineBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=_ts(2020, 1, 1), range_end=self.chunk_end,
            chunk_start=self.chunk_start, pending_tasks=1, batch_id=1,
        )

    def test_advances_raw_entry_through_pipeline_and_decrements_pending_tasks(self):
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        # PM25_LCS_Correction always merges A/B into a sensor='' CORRECTED entry
        # (see build_entry(sensor='') in PM25_LCS_Correction.process()).
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert self.job.entries_processed == 1

    def test_stale_batch_id_still_processes_but_does_not_decrement(self):
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_second_sensor_with_no_derived_entries_is_processed_independently(self):
        # PurpleAir dual-sensor: sensor 'b' has its own RAW row; find_incomplete_pipelines
        # (Task 9, revised) selects by derived_entries__isnull=True per RAW row, so both
        # sensors' RAW entries are attempted independently in the same chunk call.
        raw_b = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='b', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.2'),
        )
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        # Sensor 'a' (lexically first) produces the merged CORRECTED entry; sensor 'b'
        # legitimately produces no entry of its own (PM25_LCS_Correction defers to 'a') —
        # both RAW rows were still attempted (entries_processed counts both).
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.entries_processed == 2


from camp.apps.monitors.tasks import reprocess_legacy_pipeline_tick


class ReprocessLegacyPipelineTickTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2023, 1, 1)
        self.range_end = _ts(2023, 1, 22)
        self.early = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.range_start + timedelta(hours=1),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('10.0'),
        )
        self.late = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.range_end - timedelta(hours=1),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('10.0'),
        )
        self.job = PipelineBackfillJob.objects.create(
            cursor=self.range_start, range_start=self.range_start, range_end=self.range_end, chunk_days=7,
        )

    def _corrected_at(self, raw):
        return entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=raw.timestamp, stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()

    def _tick(self):
        with self.captureOnCommitCallbacks(execute=True):
            reprocess_legacy_pipeline_tick()
        PipelineBackfillJob.objects.filter(pk=self.job.pk).update(locked_at=None)
        self.job.refresh_from_db()

    def test_first_chunk_is_the_oldest(self):
        self._tick()
        assert self.job.chunk_start == self.range_start
        assert self.job.pending_tasks == 0
        assert self._corrected_at(self.early)
        assert not self._corrected_at(self.late)

    def test_cursor_walks_forward_to_done(self):
        for _ in range(6):  # 3 chunks x (dispatch + complete)
            self._tick()
        assert self.job.cursor == self.range_end
        assert self.job.state == PipelineBackfillJob.State.DONE
        assert self._corrected_at(self.early)
        assert self._corrected_at(self.late)

    def test_last_chunk_is_clamped_to_range_end(self):
        self.job.range_end = self.range_start + timedelta(days=10)
        self.job.save()
        for _ in range(4):
            self._tick()
        assert self.job.cursor == self.range_start + timedelta(days=10)
        assert self.job.state == PipelineBackfillJob.State.DONE

    def test_no_op_when_no_running_job(self):
        self.job.state = PipelineBackfillJob.State.DONE
        self.job.save()
        reprocess_legacy_pipeline_tick()  # should not raise


class ReprocessLegacyPipelineTickStalenessTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2020, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        self.job = PipelineBackfillJob.objects.create(
            cursor=self.range_start, range_start=self.range_start, range_end=self.range_end,
            chunk_start=self.range_start, pending_tasks=1, batch_id=1,
            phase_started_at=timezone.now() - timedelta(minutes=61),
        )

    def test_stale_batch_is_restarted(self):
        with self.captureOnCommitCallbacks(execute=True):
            reprocess_legacy_pipeline_tick()
        self.job.refresh_from_db()
        assert self.job.batch_id != 1
        assert self.job.consecutive_failures == 1
        assert self.job.state == PipelineBackfillJob.State.RUNNING

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ADMINS=[('Test Admin', 'admin@example.com')],
    )
    def test_repeated_staleness_eventually_marks_job_failed(self):
        self.job.consecutive_failures = 4  # one below the threshold of 5
        self.job.save()
        with self.captureOnCommitCallbacks(execute=True):
            reprocess_legacy_pipeline_tick()
        self.job.refresh_from_db()
        assert self.job.state == PipelineBackfillJob.State.FAILED
        assert self.job.pending_tasks == 0

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == '[SJVAir] Legacy pipeline reprocessing failed'
        assert list(mail.outbox[0].to) == ['admin@example.com']



    def test_slow_batch_with_recent_progress_is_not_restarted(self):
        self.job.last_progress_at = timezone.now() - timedelta(minutes=5)
        self.job.save()
        reprocess_legacy_pipeline_tick()
        self.job.refresh_from_db()
        assert self.job.batch_id == 1

    def test_failed_job_clears_chunk_start(self):
        self.job.consecutive_failures = 4
        self.job.save()
        with self.captureOnCommitCallbacks(execute=True):
            reprocess_legacy_pipeline_tick()
        self.job.refresh_from_db()
        assert self.job.state == PipelineBackfillJob.State.FAILED
        assert self.job.chunk_start is None


class ReprocessMonitorChunkResilienceTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_one_failing_entry_does_not_stop_the_chunk(self):
        from unittest.mock import patch

        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        for minutes in (0, 2):
            entry_models.PM25.objects.create(
                monitor=monitor, sensor='a', timestamp=ts + timedelta(minutes=minutes),
                location=monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
                value=Decimal('10.0'),
            )
        job = PipelineBackfillJob.objects.create(
            cursor=ts, range_start=ts, range_end=ts + timedelta(hours=1),
            chunk_start=ts, pending_tasks=1, batch_id=1,
        )
        original = PurpleAir.process_entry_pipeline
        calls = []

        def flaky(self, entry, cutoff_stage=None):
            calls.append(entry.pk)
            if len(calls) == 1:
                raise RuntimeError('boom')
            return original(self, entry, cutoff_stage)

        with patch.object(PurpleAir, 'process_entry_pipeline', flaky):
            reprocess_monitor_chunk(job.pk, str(monitor.pk), ts, ts + timedelta(hours=1), 1)

        assert len(set(calls)) >= 2  # the second RAW entry was still attempted
        job.refresh_from_db()
        assert job.pending_tasks == 0
        assert job.entries_processed == 1


class ReprocessLegacyPipelineCommandTests(TestCase):
    def test_start_creates_job(self):
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', stdout=out)
        assert PipelineBackfillJob.objects.filter(state=PipelineBackfillJob.State.RUNNING).exists()
        assert 'Started' in out.getvalue()

    def test_default_range_end_stays_behind_live_ingestion(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', stdout=StringIO())
        job = PipelineBackfillJob.objects.get()
        assert job.range_end <= timezone.now() - timedelta(hours=23)

    def test_start_puts_cursor_at_oldest_date(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', '--to', '2020-02-01',
            stdout=StringIO())
        job = PipelineBackfillJob.objects.get()
        assert job.cursor == job.range_start

    def test_status_progress_counts_forward(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', '--to', '2020-01-11',
            stdout=StringIO())
        job = PipelineBackfillJob.objects.get()
        PipelineBackfillJob.objects.filter(pk=job.pk).update(cursor=job.range_start + timedelta(days=4))
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'status', stdout=out)
        assert 'Progress: 40.0%' in out.getvalue()

    def test_start_refuses_second_job_without_force(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
        try:
            call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert PipelineBackfillJob.objects.count() == 1

    def test_status_with_no_job(self):
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'status', stdout=out)
        assert 'No backfill job' in out.getvalue()

    def test_cancel_sets_state_done(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
        call_command('reprocess_legacy_pipeline', 'cancel')
        job = PipelineBackfillJob.objects.first()
        assert job.state == PipelineBackfillJob.State.DONE

    def test_start_raises_command_error_on_invalid_date_values(self):
        try:
            call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-13-40')
            assert False, 'expected CommandError'
        except CommandError:
            pass

    def test_force_does_not_delete_existing_job_when_new_dates_invalid(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
        try:
            call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-13-40', '--force')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert PipelineBackfillJob.objects.count() == 1
        job = PipelineBackfillJob.objects.first()
        assert job.range_start.year == 2020 and job.range_start.month == 1 and job.range_start.day == 1


class FixPurpleAirPressureCommandTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts,
            location=self.monitor.location, pressure=Decimal('1013.25'),
        )

    def test_corrects_mislabeled_hpa_value(self):
        # Simulate the old buggy migration: raw hPa copied directly into `value`.
        bad_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        out = StringIO()
        call_command('fix_purpleair_pressure', stdout=out)
        bad_entry.refresh_from_db()
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert bad_entry.value == expected
        assert 'Corrected 1' in out.getvalue()

    def test_leaves_already_correct_value_untouched(self):
        correct_value = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        good_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=correct_value,
        )
        out = StringIO()
        call_command('fix_purpleair_pressure', stdout=out)
        good_entry.refresh_from_db()
        assert good_entry.value == correct_value
        assert 'Corrected 0' in out.getvalue()

    def test_dry_run_does_not_modify(self):
        bad_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        call_command('fix_purpleair_pressure', '--dry-run')
        bad_entry.refresh_from_db()
        assert bad_entry.value == Decimal('1013.25')

    def test_monitor_flag_scopes_to_one_monitor(self):
        bad_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        out = StringIO()
        call_command('fix_purpleair_pressure', '--monitor', str(self.monitor.pk), stdout=out)
        bad_entry.refresh_from_db()
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert bad_entry.value == expected
        assert 'Corrected 1' in out.getvalue()

    def test_monitor_flag_raises_on_unknown_id(self):
        from django_smalluuid.models import uuid_default
        unknown_id = str(uuid_default()())
        try:
            call_command('fix_purpleair_pressure', '--monitor', unknown_id)
            assert False, 'expected CommandError'
        except CommandError:
            pass

    def test_from_to_flags_scope_the_date_range(self):
        in_range_ts = self.ts
        out_of_range_ts = self.ts + timedelta(days=30)

        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=out_of_range_ts,
            location=self.monitor.location, pressure=Decimal('1013.25'),
        )
        in_range_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=in_range_ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        out_of_range_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=out_of_range_ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )

        out = StringIO()
        call_command(
            'fix_purpleair_pressure',
            '--from', in_range_ts.strftime('%Y-%m-%d'),
            '--to', (in_range_ts + timedelta(days=1)).strftime('%Y-%m-%d'),
            stdout=out,
        )

        in_range_entry.refresh_from_db()
        out_of_range_entry.refresh_from_db()
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert in_range_entry.value == expected
        assert out_of_range_entry.value == Decimal('1013.25')  # untouched, outside --to
        assert 'Corrected 1 of 1 checked' in out.getvalue()


class LegacyBackfillThenReprocessIntegrationTests(TestCase):
    '''
    Final-review Finding 2 regression test: exercises BOTH job systems
    together (backfill_monitor_chunk then reprocess_monitor_chunk) on real
    data, covering a monitor type/pipeline shape that no prior test did --
    this is exactly the gap that let Finding 1's cutoff_stage bug through.
    Finding 1: passing pipeline_entry_models()'s terminal stage in as
    cutoff_stage made single-stage (RAW->CLEANED / RAW->CALIBRATED)
    pipelines a complete no-op, and made PurpleAir's multi-stage PM25
    pipeline stop one stage short of CALIBRATED.
    '''
    fixtures = ['purple-air.yaml']

    def test_backfilled_raw_entries_are_reprocessed_for_purpleair(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk, reprocess_monitor_chunk

        monitor = PurpleAir.objects.first()
        chunk_start = _ts(2023, 1, 1)
        chunk_end = _ts(2023, 1, 8)
        ts = chunk_start + timedelta(hours=1)

        for sensor, value in (('a', Decimal('12.0')), ('b', Decimal('12.2'))):
            Entry.objects.create(
                monitor=monitor, sensor=sensor, timestamp=ts,
                location=monitor.location, pm25_reported=value,
            )

        entry_job = EntryBackfillJob.objects.create(
            cursor=chunk_end, range_start=_ts(2020, 1, 1), range_end=chunk_end,
            chunk_start=chunk_start, pending_tasks=1, batch_id=1,
        )
        backfill_monitor_chunk(entry_job.pk, str(monitor.pk), chunk_start, chunk_end, 1)

        raw = entry_models.PM25.objects.get(
            monitor=monitor, sensor='a', timestamp=ts, stage=entry_models.PM25.Stage.RAW,
        )
        assert raw.value == Decimal('12.0')

        pipeline_job = PipelineBackfillJob.objects.create(
            cursor=chunk_end, range_start=_ts(2020, 1, 1), range_end=chunk_end,
            chunk_start=chunk_start, pending_tasks=1, batch_id=1,
        )
        reprocess_monitor_chunk(pipeline_job.pk, str(monitor.pk), chunk_start, chunk_end, 1)

        # The first processor (RAW->CORRECTED) must run on the backfilled rows.
        assert entry_models.PM25.objects.filter(
            monitor=monitor, timestamp=ts, stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()

    def test_multi_stage_pipeline_reaches_calibrated_for_purpleair(self):
        from camp.apps.monitors.tasks import reprocess_monitor_chunk

        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        chunk_start = ts
        chunk_end = ts + timedelta(hours=1)

        entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.0'),
        )
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='b', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.2'),
        )
        # Humidity RAW entry so PM25_EPA_Oct2021's required_context (['pm25',
        # 'humidity']) is satisfiable at the CLEANED->CALIBRATED step --
        # entry_context() looks up Humidity at its default_stage (RAW),
        # regardless of sensor.
        entry_models.Humidity.objects.create(
            monitor=monitor, sensor='', timestamp=ts, location=monitor.location,
            stage=entry_models.Humidity.Stage.RAW, processor='', value=Decimal('40.0'),
        )
        # PM25_LCS_Cleaning (CORRECTED->CLEANED) defers whenever there's no
        # later CORRECTED entry at all (get_next_entry() is None) -- by
        # design, it won't finalize "the latest known entry". Pre-seed a
        # later CORRECTED entry directly (bypassing the pipeline) so
        # cleaning doesn't defer for our target timestamp.
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='', timestamp=ts + timedelta(hours=1),
            location=monitor.location, stage=entry_models.PM25.Stage.CORRECTED,
            processor='PM25_LCS_Correction', value=Decimal('10.1'),
        )

        pipeline_job = PipelineBackfillJob.objects.create(
            cursor=chunk_end, range_start=_ts(2020, 1, 1), range_end=chunk_end,
            chunk_start=chunk_start, pending_tasks=1, batch_id=1,
        )
        reprocess_monitor_chunk(pipeline_job.pk, str(monitor.pk), chunk_start, chunk_end, 1)

        # PurpleAir's PM25 pipeline is RAW->CORRECTED->CLEANED->CALIBRATED.
        # With the Finding 1 bug, cutoff_stage=CALIBRATED skipped the
        # CLEANED->CALIBRATED processors, stopping one stage short. This
        # proves the full chain now completes (via PM25_EPA_Oct2021, which
        # needs no trained Calibration model, unlike the linear-regression
        # processors).
        assert entry_models.PM25.objects.filter(
            monitor=monitor, timestamp=ts, sensor='', stage=entry_models.PM25.Stage.CALIBRATED,
        ).exists()


    def test_migrated_cleaned_entry_without_calibration_reaches_calibrated(self):
        # Review item 2: an earlier migration left PurpleAir PM2.5 with RAW,
        # CORRECTED and CLEANED but no CALIBRATED. Reprocessing continues from
        # the CLEANED entry.
        from camp.apps.monitors.tasks import reprocess_monitor_chunk

        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        raw = entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.0'),
        )
        corrected = entry_models.PM25.objects.create(
            monitor=monitor, sensor='', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.CORRECTED, processor='PM25_LCS_Correction',
            value=Decimal('10.0'), origin=raw,
        )
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.CLEANED, processor='PM25_LCS_Cleaning',
            value=Decimal('10.0'), origin=corrected,
        )
        entry_models.Humidity.objects.create(
            monitor=monitor, sensor='', timestamp=ts, location=monitor.location,
            stage=entry_models.Humidity.Stage.RAW, processor='', value=Decimal('40.0'),
        )

        job = PipelineBackfillJob.objects.create(
            cursor=ts, range_start=ts, range_end=ts + timedelta(hours=1),
            chunk_start=ts, pending_tasks=1, batch_id=1,
        )
        reprocess_monitor_chunk(job.pk, str(monitor.pk), ts, ts + timedelta(hours=1), 1)

        assert entry_models.PM25.objects.filter(
            monitor=monitor, timestamp=ts, sensor='', stage=entry_models.PM25.Stage.CALIBRATED,
            processor='PM25_EPA_Oct2021',
        ).exists()

class ReprocessSpikeSmoothingTests(TestCase):
    """
    Review finding: reprocessing walked RAW entries newest-first, so
    PM25_LCS_Cleaning never had a previous CORRECTED entry and every
    reprocessed CLEANED value equalled its CORRECTED value (spikes kept).
    """
    fixtures = ['purple-air.yaml']

    def test_spike_is_smoothed_in_reprocessed_history(self):
        from camp.apps.monitors.tasks import reprocess_monitor_chunk

        monitor = PurpleAir.objects.first()
        start = _ts(2023, 1, 1)
        values = ['10.0', '10.0', '100.0', '10.0', '10.0']
        timestamps = [start + timedelta(minutes=2 * i) for i in range(len(values))]
        for ts, value in zip(timestamps, values):
            for sensor in ('a', 'b'):
                entry_models.PM25.objects.create(
                    monitor=monitor, sensor=sensor, timestamp=ts, location=monitor.location,
                    stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal(value),
                )

        job = PipelineBackfillJob.objects.create(
            cursor=start, range_start=start, range_end=start + timedelta(hours=1),
            chunk_start=start, pending_tasks=1, batch_id=1,
        )
        reprocess_monitor_chunk(job.pk, str(monitor.pk), start, start + timedelta(hours=1), 1)

        spike_ts = timestamps[2]
        corrected = entry_models.PM25.objects.get(
            monitor=monitor, timestamp=spike_ts, stage=entry_models.PM25.Stage.CORRECTED,
        )
        cleaned = entry_models.PM25.objects.get(
            monitor=monitor, timestamp=spike_ts, stage=entry_models.PM25.Stage.CLEANED,
        )
        assert cleaned.value < corrected.value


class PmColumnCutoverTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.pm10_map = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM10]
        self.pm100_map = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM100]

    def _build(self, timestamp, pm10, pm100):
        legacy = _legacy_entry(
            self.monitor, sensor='a', timestamp=timestamp,
            pm10=None if pm10 is None else Decimal(pm10),
            pm100=None if pm100 is None else Decimal(pm100),
        )
        return (
            build_raw_entry(self.monitor, legacy, entry_models.PM10, self.pm10_map),
            build_raw_entry(self.monitor, legacy, entry_models.PM100, self.pm100_map),
        )

    def test_pre_cutover_swapped_row_is_ordered(self):
        pm1, pm10 = self._build(_ts(2019, 6, 1), '9', '3')
        assert pm1.value == Decimal('3')
        assert pm10.value == Decimal('9')
        assert pm1.sensor == 'a'

    def test_pre_cutover_ordered_row_is_unchanged(self):
        pm1, pm10 = self._build(_ts(2021, 6, 1), '3', '9')
        assert pm1.value == Decimal('3')
        assert pm10.value == Decimal('9')

    def test_pre_cutover_row_with_a_null_is_skipped_for_both(self):
        assert self._build(_ts(2019, 6, 1), '3', None) == (None, None)
        assert self._build(_ts(2019, 6, 1), None, '9') == (None, None)

    def test_post_cutover_glitch_is_copied_verbatim(self):
        pm1, pm10 = self._build(_ts(2023, 6, 1), '9', '3')
        assert pm1.value == Decimal('9')
        assert pm10.value == Decimal('3')

    def test_post_cutover_single_value_is_copied(self):
        pm1, pm10 = self._build(_ts(2023, 6, 1), '3', None)
        assert pm1.value == Decimal('3')
        assert pm10 is None

    def test_cutover_boundary_counts_as_post(self):
        pm1, pm10 = self._build(PM_COLUMN_CUTOVER, '9', '3')
        assert pm1.value == Decimal('9')
        assert pm10.value == Decimal('3')
        pm1, pm10 = self._build(PM_COLUMN_CUTOVER - timedelta(seconds=1), '9', '3')
        assert pm1.value == Decimal('3')
        assert pm10.value == Decimal('9')

    def test_find_missing_raw_entries_yields_corrected_values(self):
        start = _ts(2019, 6, 1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=start + timedelta(hours=1),
            location=self.monitor.location, pm10=Decimal('9'), pm100=Decimal('3'),
        )
        end = start + timedelta(days=1)
        pm1 = find_missing_raw_entries(self.monitor, entry_models.PM10, self.pm10_map, start, end)
        pm10 = find_missing_raw_entries(self.monitor, entry_models.PM100, self.pm100_map, start, end)
        assert [e.value for e in pm1] == [Decimal('3')]
        assert [e.value for e in pm10] == [Decimal('9')]

    def test_chunk_backfill_writes_corrected_values(self):
        from camp.apps.monitors.tasks import backfill_monitor_chunk
        start, end = _ts(2019, 6, 1), _ts(2019, 6, 8)
        job = EntryBackfillJob.objects.create(
            cursor=end, range_start=_ts(2017, 1, 1), range_end=end,
            chunk_start=start, pending_tasks=1, batch_id=1,
        )
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=start + timedelta(hours=1),
            location=self.monitor.location, pm10=Decimal('9'), pm100=Decimal('3'),
        )
        backfill_monitor_chunk(job.pk, str(self.monitor.pk), start, end, 1)
        raw = entry_models.PM10.Stage.RAW
        assert entry_models.PM10.objects.get(monitor=self.monitor, stage=raw).value == Decimal('3')
        assert entry_models.PM100.objects.get(monitor=self.monitor, stage=raw).value == Decimal('9')
