import time

from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides import rollup


class Command(BaseCommand):
    help = 'Rebuild the per-section, per-month PesticideUse rollup for one year or all loaded years.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--year', type=int)
        group.add_argument('--all', action='store_true')

    def handle(self, *args, **options):
        years = rollup.loaded_years() if options['all'] else [options['year']]
        if not years:
            raise CommandError('No PesticideUse rows loaded.')
        for year in years:
            started = time.monotonic()
            written = rollup.rebuild_year(year)
            self.stdout.write(f'{year}: {written:,} rollup rows in {time.monotonic() - started:.1f}s')

        from camp.apps.pesticides import stats
        stats.refresh_landing_stats()
        self.stdout.write('Refreshed cached year facts and landing stats.')
