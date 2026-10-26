from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

import pytest

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import (
    find_incomplete_pipelines, monitors_with_incomplete_pipelines_in, processable_stages,
)
from camp.apps.monitors.models import Entry, EntryBackfillJob, LatestEntry, PipelineBackfillJob
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.tasks import backfill_monitor_chunk, reprocess_monitor_chunk

Stage = entry_models.PM25.Stage


class ReprocessChunkTestCase(TestCase):
    fixtures = ['purple-air.yaml']
    count = 12

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = datetime(2021, 6, 1, tzinfo=dt_timezone.utc)
        self.end = self.start + timedelta(minutes=2 * self.count)

    def make_raw_entries(self, count=None):
        # Values must vary: PM25_LCS_Correction discards repeated values.
        count = count or self.count
        for i in range(count):
            timestamp = self.start + timedelta(minutes=2 * i)
            for sensor in ('a', 'b'):
                Entry.objects.create(
                    monitor=self.monitor, sensor=sensor, timestamp=timestamp,
                    location=self.monitor.location, position=self.monitor.position,
                    pm10=Decimal('3'), pm25=Decimal('5'), pm100=Decimal('9'),
                    pm25_reported=Decimal(6 + i * 0.37 + (0.2 if sensor == 'b' else 0)).quantize(Decimal('0.01')),
                    particles_03um=1, particles_05um=1, particles_10um=1,
                    particles_25um=1, particles_50um=1, particles_100um=1,
                    fahrenheit=Decimal(70 + i % 7), humidity=Decimal(40 + i % 5), pressure=Decimal('1000'),
                )
        job = EntryBackfillJob.objects.create(
            cursor=self.end, range_start=self.start, range_end=self.end,
            chunk_start=self.start, pending_tasks=1, batch_id=1,
        )
        backfill_monitor_chunk(job.pk, str(self.monitor.pk), self.start, self.end, 1)

    def make_job(self, **kwargs):
        return PipelineBackfillJob.objects.create(
            cursor=self.end, range_start=self.start, range_end=self.end,
            chunk_start=self.start, pending_tasks=1, batch_id=1, **kwargs,
        )

    def reprocess(self, job=None, **kwargs):
        job = job or self.make_job()
        reprocess_monitor_chunk(job.pk, str(self.monitor.pk), self.start, self.end, 1, **kwargs)
        return job

    def stage_count(self, stage):
        return entry_models.PM25.objects.filter(monitor=self.monitor, stage=stage).count()


class StopBeforeSelectionTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = datetime(2023, 1, 1, tzinfo=dt_timezone.utc)
        self.window = (self.ts, self.ts + timedelta(hours=1))
        self.cleaned = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=Stage.CLEANED, processor='PM25_LCS_Cleaning', value=Decimal('5.0'),
        )

    def test_processable_stages(self):
        assert processable_stages(PurpleAir, entry_models.PM25) == [Stage.RAW, Stage.CORRECTED, Stage.CLEANED]
        assert processable_stages(PurpleAir, entry_models.PM25, Stage.CALIBRATED) == [Stage.RAW, Stage.CORRECTED]

    def test_cleaned_entry_not_selected_while_cutoff_set(self):
        assert find_incomplete_pipelines(self.monitor, entry_models.PM25, *self.window, Stage.CALIBRATED) == []
        assert monitors_with_incomplete_pipelines_in(*self.window, Stage.CALIBRATED) == []

    def test_cleaned_entry_selected_without_cutoff(self):
        found = find_incomplete_pipelines(self.monitor, entry_models.PM25, *self.window)
        assert [e.pk for e in found] == [self.cleaned.pk]
        assert monitors_with_incomplete_pipelines_in(*self.window) == [self.monitor.pk]

    def test_raw_entry_still_selected_while_cutoff_set(self):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=Stage.RAW, processor='', value=Decimal('5.0'),
        )
        found = find_incomplete_pipelines(self.monitor, entry_models.PM25, *self.window, Stage.CALIBRATED)
        assert [e.pk for e in found] == [raw.pk]


class StopBeforeChunkTests(ReprocessChunkTestCase):
    def test_chunk_stops_at_cleaned_then_a_full_run_calibrates(self):
        self.make_raw_entries()
        job = self.make_job(stop_before=Stage.CALIBRATED)
        self.reprocess(job, stop_before=Stage.CALIBRATED)

        assert self.stage_count(Stage.CORRECTED) == self.count
        assert self.stage_count(Stage.CLEANED) > 0
        assert self.stage_count(Stage.CALIBRATED) == 0
        assert LatestEntry.objects.filter(monitor=self.monitor, stage=Stage.CALIBRATED).count() == 0

        # CLEANED entries are skipped by a staged run, but not by a full one.
        staged = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.start, self.end, Stage.CALIBRATED)
        assert Stage.CLEANED not in {e.stage for e in staged}
        full = find_incomplete_pipelines(self.monitor, entry_models.PM25, self.start, self.end)
        assert Stage.CLEANED in {e.stage for e in full}

        self.reprocess()
        assert self.stage_count(Stage.CALIBRATED) > 0

    def test_task_defaults_to_the_full_pipeline(self):
        self.make_raw_entries()
        self.reprocess()
        assert self.stage_count(Stage.CALIBRATED) > 0


class PipelineBackfillJobStopBeforeTests(TestCase):
    def test_defaults_to_blank(self):
        job = PipelineBackfillJob.objects.create(
            cursor=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
            range_start=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
            range_end=datetime(2020, 2, 1, tzinfo=dt_timezone.utc),
        )
        assert job.stop_before == ''

    def test_start_stores_the_cutoff_and_status_shows_it(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', '--to', '2020-02-01',
            '--stop-before', 'calibrated', stdout=StringIO())
        assert PipelineBackfillJob.objects.get().stop_before == 'calibrated'
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'status', stdout=out)
        assert 'Stop before: calibrated' in out.getvalue()

    def test_status_without_cutoff(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', '--to', '2020-02-01',
            stdout=StringIO())
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'status', stdout=out)
        assert 'Stop before: (none' in out.getvalue()

    def test_rejects_unknown_stage(self):
        with pytest.raises(CommandError):
            call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', '--stop-before', 'bogus')


class ReprocessMonitorReuseTests(ReprocessChunkTestCase):
    def test_monitor_is_not_reloaded_per_entry(self):
        self.make_raw_entries()
        with CaptureQueriesContext(connection) as ctx:
            self.reprocess()
        monitor_queries = [q for q in ctx.captured_queries if 'FROM "monitors_monitor"' in q['sql']]
        # One to resolve the monitor for the chunk; none per entry (was ~3 per entry).
        assert len(monitor_queries) <= 2


class ReprocessLatestEntryTests(ReprocessChunkTestCase):
    def latest_writes(self, ctx):
        return [
            q for q in ctx.captured_queries
            if 'monitors_latestentry' in q['sql'] and q['sql'].lstrip().split()[0] in ('UPDATE', 'INSERT')
        ]

    def test_latest_entry_points_at_newest_per_series(self):
        self.make_raw_entries()
        self.reprocess()

        latest = LatestEntry.objects.filter(monitor=self.monitor, entry_type='pm25')
        assert latest.filter(stage=Stage.CLEANED).exists()
        for latest_entry in latest:
            newest = (entry_models.PM25.objects
                .filter(monitor=self.monitor, stage=latest_entry.stage, processor=latest_entry.processor)
                .order_by('-timestamp').first())
            assert latest_entry.entry_id == newest.pk
            assert latest_entry.timestamp == newest.timestamp

    def test_writes_are_per_series_not_per_entry(self):
        self.make_raw_entries()
        with CaptureQueriesContext(connection) as ctx:
            self.reprocess()
        writes = self.latest_writes(ctx)
        assert 0 < len(writes) < self.count

    def test_older_chunk_does_not_move_latest_backwards(self):
        self.make_raw_entries()
        newer = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.end + timedelta(days=3),
            location=self.monitor.location, stage=Stage.CLEANED, processor='PM25_LCS_Cleaning',
            value=Decimal('7.0'),
        )
        LatestEntry.objects.create(
            monitor=self.monitor, entry_type='pm25', entry_id=newer.pk, stage=Stage.CLEANED,
            processor='PM25_LCS_Cleaning', timestamp=newer.timestamp,
        )
        self.reprocess()
        assert LatestEntry.objects.get(
            monitor=self.monitor, entry_type='pm25', stage=Stage.CLEANED,
        ).entry_id == newer.pk

    def test_failed_entry_is_not_recorded_as_newest(self):
        self.make_raw_entries()
        last = (entry_models.PM25.objects
            .filter(monitor=self.monitor, stage=Stage.RAW, sensor='a')
            .order_by('-timestamp').first())
        original = PurpleAir.process_entry_pipeline

        def flaky(monitor, entry, cutoff_stage=None):
            results = original(monitor, entry, cutoff_stage)
            if entry.pk == last.pk:
                raise RuntimeError('boom after the pipeline recorded its latest candidates')
            return results

        with patch.object(PurpleAir, 'process_entry_pipeline', flaky):
            job = self.reprocess()

        job.refresh_from_db()
        assert job.pending_tasks == 0
        # The failing entry rolled back, so nothing from it exists...
        assert not entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=last.timestamp, stage__in=[Stage.CORRECTED, Stage.CLEANED],
        ).exists()
        # ...and no LatestEntry points at (or past) it.
        for latest_entry in LatestEntry.objects.filter(monitor=self.monitor, entry_type='pm25'):
            assert latest_entry.timestamp < last.timestamp
            assert entry_models.PM25.objects.filter(pk=latest_entry.entry_id).exists()


class ReprocessQueryBudgetTests(ReprocessChunkTestCase):
    count = 30

    # Measured 24.5 per RAW PM2.5 entry after the reprocess optimizations
    # (31.4 before); bound has ~20% headroom.
    MAX_QUERIES_PER_ENTRY = 29.5

    def test_queries_per_raw_pm25_entry(self):
        self.make_raw_entries()
        raw = self.stage_count(Stage.RAW)
        with CaptureQueriesContext(connection) as ctx:
            self.reprocess()
        assert self.stage_count(Stage.CALIBRATED) > 0
        assert len(ctx) / raw < self.MAX_QUERIES_PER_ENTRY
