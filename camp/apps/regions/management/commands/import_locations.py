from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import locations


class Command(BaseCommand):
    help = (
        'Import schools and child care facilities into regions.Location.\n'
        'Every source downloads its own file from data.ca.gov; --path reads a'
        ' local copy instead. Public schools link to their school district,'
        ' so run import_school_districts (or import_schools, which does both)'
        ' before --source cde-public.'
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

            tallies = [key for key, _ in locations.DISTRICT_TALLIES]
            summary = ', '.join(f'{key}={value}' for key, value in counts.items()
                if key not in tallies)
            self.stdout.write(f'{source}: {summary}')

            # Where the district the point falls in isn't the one the file
            # names for the address. A handful of corrections is normal --
            # overlapping elementary and high districts -- while unknown
            # districts mean the Region table is missing some.
            found = [f'{label}: {counts[key]}'
                for key, label in locations.DISTRICT_TALLIES if counts.get(key)]
            if found:
                self.stdout.write(f'{source}: districts -- ' + ', '.join(found))
