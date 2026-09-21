from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import locations


class Command(BaseCommand):
    help = (
        'Import schools and child care facilities into regions.Location.\n'
        'Sources download themselves unless --path is given. The CDE private'
        ' school affidavit is published under a new URL every year and the'
        ' CDSS facilities export changes shape, so --path is the normal route'
        ' for those (CSV; XLSX is read when openpyxl is installed).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--source', default='all',
            choices=[*locations.SOURCES.keys(), 'all'],
            help='Which source to import (default: all).')
        parser.add_argument('--path', default=None,
            help='Read a local file instead of downloading. Requires a single --source.')
        parser.add_argument('--no-geocode', dest='no_geocode', action='store_true',
            help='Skip (and count) rows that arrive without coordinates.')

    def handle(self, *args, **options):
        sources = list(locations.SOURCES) if options['source'] == 'all' else [options['source']]

        if options['path'] and len(sources) > 1:
            raise CommandError('--path requires a single --source.')

        for source in sources:
            counts = locations.import_source(
                source,
                path=options['path'],
                geocode=not options['no_geocode'],
            )
            summary = ', '.join(f'{key}={value}' for key, value in counts.items())
            self.stdout.write(f'{source}: {summary}')
