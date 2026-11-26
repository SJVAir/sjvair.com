from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.monitors.airnow.backfill import PAUSE_SECONDS, AirNowError, backfill_airnow
from camp.apps.summaries.periods import period_end, period_start
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = (
        'Re-import historical AirNow data for the valley (all parameters). PM2.5, '
        'PM10, and ozone RAW come from RawConcentration with AirNow\'s NowCast '
        'stored as CALIBRATED, and CLEANED PM2.5 is rebuilt from the new RAW. '
        'Idempotent; requests are paced to stay under AirNow\'s 500/hour limit. '
        'Summaries are not rebuilt: the closing output names the follow-up commands.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            required=True,
            help='ISO timestamp (e.g. 2020-01-01 or 2020-01-01T00:00). Naive values are treated as UTC.',
        )
        parser.add_argument(
            '--end',
            help='ISO timestamp (exclusive). Defaults to now.',
        )
        parser.add_argument(
            '--pause',
            type=float,
            default=PAUSE_SECONDS,
            help=f'Seconds to wait between requests (default {PAUSE_SECONDS}).',
        )

    def handle(self, *args, **options):
        if settings.AIRNOW_API_KEY is None:
            raise CommandError('AIRNOW_API_KEY is not set.')

        start = self.parse_timestamp(options['start'])
        end = self.parse_timestamp(options['end']) or timezone.now()
        if start >= end:
            raise CommandError('--start must be before --end')

        try:
            totals = backfill_airnow(start, end, pause=options['pause'], log=self.stdout.write)
        except (AirNowError, ValueError) as err:
            raise CommandError(str(err))

        self.stdout.write(self.style.SUCCESS(
            f'Done: {totals["entries"]} entries across {totals["monitors"]} monitors '
            f'({totals["missing"]} missing (-999) hours skipped or removed, '
            f'{totals["skipped"]} rows outside the valley skipped).'
        ))

        first = period_start('day', start)
        last = period_start('day', end)
        if last != end:
            last = period_end('day', end)
        first_date, end_date = first.date().isoformat(), last.date().isoformat()
        self.stdout.write(self.style.NOTICE(
            'Summaries are not rebuilt by this command. Next:\n'
            f'  rebuild_summaries {first_date} {end_date} --monitor=<id> --monitors-only'
            '   (per affected monitor; also fills daily figures)\n'
            f'  rebuild_summaries {first_date} {end_date} --monitor=<id> --regions-only'
            '   (per affected monitor, after the monitor rebuilds: the monitor\'s regions;\n'
            '   region rows built during the -999 period are skewed)\n'
            f'  fill_daily_peaks {first_date} {end_date} --monitor-type airnow'
            '             (at least this)'
        ))

    def parse_timestamp(self, value):
        if not value:
            return None
        try:
            return make_aware(datetime.fromisoformat(value))
        except ValueError:
            raise CommandError(f'Invalid timestamp: {value}')
