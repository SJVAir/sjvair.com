from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

# Each explorer's warm(force=False) -- see camp.utils.warm.
EXPLORERS = {
    'pesticides': 'camp.apps.pesticides.warm.warm',
    'emissions': 'camp.apps.emissions.warm.warm',
}


class Command(BaseCommand):
    help = (
        "Render the data explorers' busiest pages now, filling their caches -- what the hourly "
        "warm tasks do, for right after a deploy. Pages already warmed under the current data "
        "version are skipped unless --force."
    )

    def add_arguments(self, parser):
        parser.add_argument('explorers', nargs='*', metavar='explorer',
            help=f'Which explorers to warm: {", ".join(EXPLORERS)} (default: all).')
        parser.add_argument('--force', action='store_true',
            help='Render every page even if it is marked warm (say, after a partial cache flush). '
                 'Stats still cached are reused, not rebuilt; an import bumps the version for that.')

    def handle(self, *args, **options):
        unknown = sorted(set(options['explorers']) - set(EXPLORERS))
        if unknown:
            raise CommandError(f'Unknown explorer: {", ".join(unknown)} (choose from {", ".join(EXPLORERS)})')
        for name in options['explorers'] or EXPLORERS:
            self.stdout.write(f'{name}: warming...')
            result = import_string(EXPLORERS[name])(force=options['force'])
            self.stdout.write(
                f"{name}: {result['warmed']} warmed, {result['skipped']} already warm, "
                f"{result['failed']} failed [{result['seconds']}s]"
            )
            if result['failed']:
                self.stderr.write(f'{name}: {result["failed"]} pages failed; see the log for which.')
