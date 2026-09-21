from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import locations


class Command(BaseCommand):
    help = (
        'Import schools and child care facilities into regions.Location.\n'
        'Sources download themselves unless --path is given. The CDE private'
        ' school affidavit is published under a new URL every year, so it has'
        ' no download and --path is the only way to import it (CSV; XLSX is'
        ' read when openpyxl is installed). Under --source all it is skipped'
        ' with a message when no --path is given.'
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
        path = options['path']

        if path and len(sources) > 1:
            raise CommandError('--path requires a single --source.')

        for source in sources:
            if not path and not locations.has_download(source):
                message = f'{source}: no download available, pass --path to import it.'
                if len(sources) == 1:
                    raise CommandError(message)
                self.stdout.write(message)
                continue

            try:
                counts = locations.import_source(source, path=path,
                    geocode=not options['no_geocode'])
            except locations.DownloadError as exc:
                raise CommandError(str(exc))

            summary = ', '.join(f'{key}={value}' for key, value in counts.items())
            self.stdout.write(f'{source}: {summary}')
