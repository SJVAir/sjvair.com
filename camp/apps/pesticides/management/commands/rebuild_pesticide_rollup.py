import time

from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides import rollup


class Command(BaseCommand):
    help = 'Rebuild the per-section, per-month PesticideUse rollup for one year or all loaded years.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--year', type=int)
        group.add_argument('--all', action='store_true')
        parser.add_argument('--totals-only', action='store_true',
            help='Rebuild only the totals derived from the existing rollup: the per-county entity totals and the per-section totals.')

    def handle(self, *args, **options):
        totals_only = options['totals_only']
        if options['all']:
            years = rollup.rollup_years() if totals_only else rollup.loaded_years()
        else:
            years = [options['year']]
        if not years:
            raise CommandError('No PesticideUseRollup rows loaded.' if totals_only else 'No PesticideUse rows loaded.')
        for year in years:
            started = time.monotonic()
            if totals_only:
                written = rollup.rebuild_totals_year(year)
                label = 'total rows'
            else:
                written = rollup.rebuild_year(year)
                label = 'rollup rows'
            self.stdout.write(f'{year}: {written:,} {label} in {time.monotonic() - started:.1f}s')

        from camp.apps.pesticides import stats
        stats.refresh_landing_stats()
        self.stdout.write('Refreshed cached year facts and landing stats.')
