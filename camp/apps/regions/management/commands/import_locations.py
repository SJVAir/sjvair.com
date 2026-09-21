from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import locations


class Command(BaseCommand):
    help = (
        'Import schools and child care facilities into regions.Location.\n'
        'The CDE files (public directory, private school affidavit) cannot be'
        ' fetched server-side -- cde.ca.gov answers with a bot-protection page'
        ' -- so download them in a browser from https://www.cde.ca.gov/ds/si/ds/pubschls.asp'
        ' and https://www.cde.ca.gov/ds/si/ps/ and pass them with --path'
        ' (CSV/tab-delimited; XLSX is read when openpyxl is installed).'
        ' Under --source all, the sources that need --path are skipped with a'
        ' message.'
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
                page_url = locations.SOURCES[source].get('page_url') or 'the source site'
                message = (f'{source}: no download available; get the file from'
                    f' {page_url} and pass it with --path.')
                if len(sources) == 1:
                    raise CommandError(message)
                self.stdout.write(message)
                continue

            try:
                counts = locations.import_source(source, path=path,
                    geocode=not options['no_geocode'])
            except locations.DownloadError as exc:
                raise CommandError(str(exc))

            if not any(counts.values()):
                # Zero of everything means nothing parsed: a changed format,
                # or the wrong file. Don't let it read as a clean import.
                where = path or locations.SOURCES[source]['label']
                self.stdout.write(self.style.WARNING(
                    f'{source}: no rows parsed from {where}; nothing changed.'))
                continue

            summary = ', '.join(f'{key}={value}' for key, value in counts.items())
            self.stdout.write(f'{source}: {summary}')
