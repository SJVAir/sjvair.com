from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.airnow.relabel import FIXED_AT, relabel_nowcast
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = (
        'Relabel PM2.5, PM10, and ozone stored as RAW before the import kept '
        'RawConcentration, for sites backfill_airnow can\'t re-fetch (AirNow '
        'leaves closed sites out). Those values are AirNow\'s NowCast, so they '
        'become CALIBRATED NowCast entries and their CLEANED entries are removed. '
        'Only series with no NowCast stored are touched. Idempotent.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List the series that would change; write nothing.')
        parser.add_argument(
            '--before',
            help=f'Only relabel RAW before this ISO timestamp (default {FIXED_AT:%Y-%m-%d}, when the import was fixed). '
                 'Naive values are treated as UTC.',
        )

    def handle(self, *args, **options):
        before = FIXED_AT
        if options['before']:
            try:
                before = make_aware(datetime.fromisoformat(options['before']))
            except ValueError:
                raise CommandError(f'Invalid timestamp: {options["before"]}')

        totals = relabel_nowcast(before=before, dry_run=options['dry_run'], log=self.stdout.write)
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'Dry run: {totals["relabeled"]} RAW entries across {totals["series"]} series would be relabeled.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Done: {totals["relabeled"]} entries relabeled across {totals["series"]} series '
            f'({totals["removed"]} derived entries removed).'
        ))
