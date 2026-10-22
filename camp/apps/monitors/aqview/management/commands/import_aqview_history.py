from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.aqview.history import import_aqview_history


class Command(BaseCommand):
    help = (
        'Import historical AQview PM2.5 from CSVs (or zips) downloaded from '
        'https://aqview.arb.ca.gov/continuous-monitoring-data. Each file\'s '
        'range replaces the stored PM2.5 for its monitors; rows the provider '
        'invalidated are skipped. Idempotent.'
    )

    def add_arguments(self, parser):
        parser.add_argument('paths', nargs='+', help='Download-tool CSV or zip files.')

    def handle(self, *args, **options):
        try:
            totals = import_aqview_history(options['paths'], log=self.stdout.write)
        except FileNotFoundError as err:
            raise CommandError(str(err))

        self.stdout.write(self.style.SUCCESS(
            f'Done: {totals.get("raw", 0)} raw and {totals.get("cleaned", 0)} cleaned entries across '
            f'{totals.get("monitors", 0)} monitor ranges ({totals.get("invalid", 0)} invalidated rows skipped, '
            f'{totals.get("removed", 0)} old entries removed).'
        ))
