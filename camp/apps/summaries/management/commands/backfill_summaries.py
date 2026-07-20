from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import SummaryBackfillJob


class Command(BaseCommand):
    help = 'Start, monitor, or cancel the automated full-history summary backfill job.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'status', 'cancel'])
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest date to backfill (required for start)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to backfill, exclusive (default: start of current month)')
        parser.add_argument('--force', action='store_true',
            help='Replace an existing running/paused job instead of refusing to start a new one')

    def handle(self, *args, **options):
        action = options['action']
        if action == 'start':
            self._start(options)
        elif action == 'status':
            self._status()
        elif action == 'cancel':
            self._cancel()

    def _start(self, options):
        if not options['date_from']:
            raise CommandError('--from is required for start')

        active = SummaryBackfillJob.objects.filter(
            state__in=[SummaryBackfillJob.State.RUNNING, SummaryBackfillJob.State.PAUSED],
        ).first()
        if active and not options['force']:
            raise CommandError(
                f'A backfill job is already {active.state} (cursor {active.cursor:%Y-%m-%d}). '
                'Pass --force to replace it.'
            )
        if active and options['force']:
            active.delete()

        range_start = self._parse_date(options['date_from'])
        range_end = (
            self._parse_date(options['date_to'])
            if options['date_to']
            else self._start_of_current_month()
        )
        if range_start >= range_end:
            raise CommandError('--from must be before --to')

        SummaryBackfillJob.objects.create(
            cursor=range_end,
            range_start=range_start,
            range_end=range_end,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Started backfill job: {range_start:%Y-%m-%d} → {range_end:%Y-%m-%d}'
        ))

    def _status(self):
        job = SummaryBackfillJob.objects.order_by('-created').first()
        if job is None:
            self.stdout.write('No backfill job has been started.')
            return

        total_seconds = (job.range_end - job.range_start).total_seconds()
        done_seconds = (job.range_end - job.cursor).total_seconds()
        percent = 100 * done_seconds / total_seconds if total_seconds else 100

        self.stdout.write(f'State: {job.state}')
        self.stdout.write(f'Phase: {job.phase}')
        self.stdout.write(f'Cursor: {job.cursor:%Y-%m-%d}')
        self.stdout.write(f'Range: {job.range_start:%Y-%m-%d} → {job.range_end:%Y-%m-%d}')
        self.stdout.write(f'Progress: {percent:.1f}%')
        if job.last_error:
            self.stdout.write(self.style.WARNING(f'Last error: {job.last_error}'))

    def _cancel(self):
        job = SummaryBackfillJob.objects.filter(
            state__in=[SummaryBackfillJob.State.RUNNING, SummaryBackfillJob.State.PAUSED],
        ).first()
        if job is None:
            self.stdout.write('No active backfill job to cancel.')
            return
        job.state = SummaryBackfillJob.State.DONE
        job.save(update_fields=['state'])
        self.stdout.write(self.style.SUCCESS('Backfill job cancelled.'))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)

    def _start_of_current_month(self):
        today = timezone.localtime(timezone.now(), settings.DEFAULT_TIMEZONE).date()
        return make_aware(datetime(today.year, today.month, 1), settings.DEFAULT_TIMEZONE)
