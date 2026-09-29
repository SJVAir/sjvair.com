import os

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import nei


class Command(BaseCommand):
    help = (
        "Import county ammonia (NH3) from EPA's National Emissions Inventory for the covered counties: the county x "
        'sector summary and the nonpoint livestock split. Streams both zips (never unpacked). Idempotent per year. '
        'Downloads the two zips for the year unless --sector-path / --nonpoint-path name local copies.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='NEI year (2023)')
        parser.add_argument('--sector-path', help='A downloaded county x sector "allpolls" zip')
        parser.add_argument('--nonpoint-path', help='A downloaded nonpoint county x SCC zip')

    def handle(self, *args, **options):
        year = options['year']
        sector_path = options['sector_path']
        nonpoint_path = options['nonpoint_path']
        temp = []
        try:
            if sector_path is None or nonpoint_path is None:
                if year not in nei.URLS:
                    raise CommandError(f'No download URLs for NEI {year}; pass --sector-path and --nonpoint-path (or add the year to nei.URLS).')
                sector_url, nonpoint_url = nei.URLS[year]
                if sector_path is None:
                    self.stdout.write(f'Downloading {sector_url}')
                    sector_path = nei.download(sector_url)
                    temp.append(sector_path)
                if nonpoint_path is None:
                    self.stdout.write(f'Downloading {nonpoint_url}')
                    nonpoint_path = nei.download(nonpoint_url)
                    temp.append(nonpoint_path)
            fips = set(nei.county_fips())
            try:
                self.stdout.write('Reading the county x sector summary...')
                sector_rows = nei.read_sector(sector_path, fips)
                self.stdout.write('Reading the nonpoint livestock rows (a 2.8 GB CSV; a few minutes)...')
                nonpoint_rows = nei.read_nonpoint(nonpoint_path, fips)
            except nei.NEIFormatError as err:
                raise CommandError(str(err))
        finally:
            for path in temp:
                os.unlink(path)
        if not sector_rows:
            raise CommandError('No NH3 rows for the covered counties; nothing written.')
        report = nei.apply(year, sector_rows, nonpoint_rows)
        for line in report.lines():
            self.stdout.write(line)
