from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.apps.monitors.purpleair.history import estimate
from camp.apps.monitors.purpleair.models import PurpleAir, PurpleAirHistoryGap, PurpleAirHistoryJob
from camp.apps.monitors.purpleair.tasks import import_purpleair_history_chunk
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = 'Start, monitor, cancel, or retry the PurpleAir API history import job.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'status', 'cancel', 'retry'])
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest date to import (required for start)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to import, exclusive (default: 24 hours ago)')
        parser.add_argument('--monitor-id', dest='monitor_ids', action='append', default=[],
            help='Only import this monitor (repeatable)')
        parser.add_argument('--chunk-days', dest='chunk_days', type=int, default=28,
            help='Days per request window (default: 28)')
        parser.add_argument('--force', action='store_true',
            help='Replace an existing running/paused job instead of refusing to start a new one')
        parser.add_argument('--dry-run', action='store_true',
            help='With start: print the monitors, windows, requests and data points, and create nothing')

    def handle(self, *args, **options):
        getattr(self, f'_{options["action"]}')(options)

    def _active(self):
        return PurpleAirHistoryJob.objects.filter(
            state__in=[PurpleAirHistoryJob.State.RUNNING, PurpleAirHistoryJob.State.PAUSED],
        ).first()

    def _start(self, options):
        if not options['date_from']:
            raise CommandError('--from is required for start')

        chunk_days = options['chunk_days']
        if chunk_days < 1:
            raise CommandError('--chunk-days must be at least 1')

        range_start = self._parse_date(options['date_from'])
        range_end = (
            self._parse_date(options['date_to'])
            if options['date_to']
            else timezone.now() - timedelta(hours=24)
        )
        if range_start >= range_end:
            raise CommandError('--from must be before --to')

        monitor_ids = options['monitor_ids']
        if monitor_ids:
            try:
                found = {str(pk) for pk in PurpleAir.objects.filter(pk__in=monitor_ids).values_list('pk', flat=True)}
            except ValidationError as error:
                raise CommandError(f'Invalid monitor id: {error.messages[0]}')
            missing = [m for m in monitor_ids if m not in found]
            if missing:
                raise CommandError(f'Unknown PurpleAir monitor id(s): {", ".join(missing)}')

        if options['dry_run']:
            windows, requests, data_points = estimate(range_start, range_end, chunk_days, monitor_ids)
            monitors = PurpleAir.objects.filter(sensor_id__isnull=False)
            if monitor_ids:
                monitors = monitors.filter(pk__in=monitor_ids)
            self.stdout.write(f'Monitors: {monitors.count()}')
            self.stdout.write(f'Windows: {windows} ({chunk_days}-day)')
            self.stdout.write(f'Requests: {requests}')
            self.stdout.write(f'Estimated data points: {data_points}')
            return

        active = self._active()
        if active and not options['force']:
            raise CommandError(
                f'An import job is already {active.state} (cursor {active.cursor:%Y-%m-%d}). '
                'Pass --force to replace it.'
            )

        with transaction.atomic():
            if active:
                active.delete()

            PurpleAirHistoryJob.objects.create(
                cursor=range_end,
                range_start=range_start,
                range_end=range_end,
                chunk_days=chunk_days,
                monitor_ids=monitor_ids,
            )
        self.stdout.write(self.style.SUCCESS(
            f'Started PurpleAir history import: {range_start:%Y-%m-%d} -> {range_end:%Y-%m-%d} '
            f'({chunk_days}-day windows)'
        ))

    def _status(self, options):
        job = PurpleAirHistoryJob.objects.order_by('-created').first()
        if job is None:
            self.stdout.write('No import job has been started.')
            return

        total_seconds = (job.range_end - job.range_start).total_seconds()
        done_seconds = (job.range_end - job.cursor).total_seconds()
        percent = 100 * done_seconds / total_seconds if total_seconds else 100

        self.stdout.write(f'State: {job.state}')
        self.stdout.write(f'Cursor: {job.cursor:%Y-%m-%d}')
        self.stdout.write(f'Range: {job.range_start:%Y-%m-%d} -> {job.range_end:%Y-%m-%d}')
        self.stdout.write(f'Window size: {job.chunk_days} day(s)')
        self.stdout.write(f'Progress: {percent:.1f}%')
        self.stdout.write(f'Requests: {job.requests_made}')
        self.stdout.write(f'Rows fetched: {job.rows_fetched}')
        self.stdout.write(f'Data points: {job.data_points}')
        self.stdout.write(f'RAW entries created: {job.raw_entries_created}')
        if job.last_error:
            self.stdout.write(self.style.WARNING(f'Last error: {job.last_error}'))

        gaps = job.gaps.select_related('monitor').order_by('monitor_id', 'window_start')
        if gaps:
            self.stdout.write(self.style.WARNING(f'Gaps: {len(gaps)}'))
            for gap in gaps:
                self.stdout.write(
                    f'  {gap.reason}: {gap.monitor_id} {gap.window_start:%Y-%m-%d} -> '
                    f'{gap.window_end:%Y-%m-%d} {gap.message}'
                )

    def _cancel(self, options):
        job = self._active()
        if job is None:
            self.stdout.write('No active import job to cancel.')
            return
        job.state = PurpleAirHistoryJob.State.DONE
        job.save(update_fields=['state'])
        self.stdout.write(self.style.SUCCESS('Import job cancelled.'))

    def _retry(self, options):
        job = PurpleAirHistoryJob.objects.order_by('-created').first()
        gaps = list(job.gaps.all()) if job else []
        if not gaps:
            self.stdout.write('No gaps to retry.')
            return

        # Each task records a fresh gap if its window fails again.
        job.gaps.all().delete()
        for gap in gaps:
            import_purpleair_history_chunk(job.pk, str(gap.monitor_id), gap.window_start, gap.window_end)
        self.stdout.write(self.style.SUCCESS(f'Retrying {len(gaps)} gap(s).'))

    def _parse_date(self, value):
        try:
            d = parse_date(value)
        except ValueError:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
