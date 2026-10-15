import time

from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides import rollup


class Command(BaseCommand):
    help = (
        'Rebuild the per-section, per-month PesticideUse rollup for one year or all loaded years. '
        'Rerun with --all after the flagged/restricted chemical lists change (import_prop65, '
        'import_carbtac, import_comptox hazard, import_restricted_materials): the rollup picks '
        'each record\'s counted ingredient from them, so narrowed application counts are only '
        'exact after a full rebuild.'
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--year', type=int)
        group.add_argument('--all', action='store_true')
        group.add_argument('--fumigants-only', action='store_true',
            help='Only reclassify fumigant products and ingredients over all loaded years; leave the rollup alone.')
        parser.add_argument('--totals-only', action='store_true',
            help='Rebuild only the totals derived from the existing rollup: the per-county entity totals and the per-section totals.')

    def handle(self, *args, **options):
        from camp.apps.pesticides import fumigants, stats

        if options['fumigants_only']:
            self.write_fumigants(fumigants.classify_fumigants())
            stats.refresh_landing_stats()
            self.stdout.write('Refreshed cached year facts and landing stats.')
            return

        totals_only = options['totals_only']
        if options['all']:
            years = rollup.rollup_years() if totals_only else rollup.loaded_years()
            years.reverse()  # newest first, so the default page year has data soonest
        else:
            years = [options['year']]
        if not years:
            raise CommandError('No PesticideUseRollup rows loaded.' if totals_only else 'No PesticideUse rows loaded.')
        if options['all'] and not totals_only:
            # Before the year loop: it reads PesticideUse, not the rollup, so
            # fumigants are flagged from the start rather than after the rebuild.
            self.write_fumigants(fumigants.classify_fumigants())
        for year in years:
            started = time.monotonic()
            if totals_only:
                written = rollup.rebuild_totals_year(year)
                label = 'total rows'
            else:
                written = rollup.rebuild_year(year)
                label = 'rollup rows'
            self.stdout.write(f'{year}: {written:,} {label} in {time.monotonic() - started:.1f}s')

        stats.refresh_landing_stats()
        self.stdout.write('Refreshed cached year facts and landing stats.')

    def write_fumigants(self, counts):
        self.stdout.write(
            f"Fumigants: {counts['chemicals']:,} chemicals, {counts['products']:,} products "
            f"({counts['added']:,} not flagged by CDPR)"
        )
