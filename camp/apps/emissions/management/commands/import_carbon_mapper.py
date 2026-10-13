from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions.importers import carbonmapper


class Command(BaseCommand):
    help = (
        "Import Carbon Mapper's methane point sources for the Valley bbox (about 730; under a minute). Keeps CH4 sources inside "
        'the covered counties, links each to the nearest dairy and trusted-point facility within 1 km, removes sources no longer '
        "in the catalog. Then pages through the sources' plumes (about 2,550), links each to the nearest source within 1 km, and "
        "fetches any new plume's image. Idempotent. Data under Carbon Mapper's non-commercial terms (https://carbonmapper.org/terms). "
        '--path reads a saved sources CSV instead of the API. --no-plumes skips the plume step.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A saved sources CSV to import instead of fetching')
        parser.add_argument('--no-plumes', action='store_true', help='Skip importing plumes and their images')

    def handle(self, *args, **options):
        try:
            text = Path(options['path']).read_text() if options['path'] else carbonmapper.fetch_csv()
            rows = carbonmapper.read_rows(text)
        except (carbonmapper.CarbonMapperError, OSError, requests.RequestException) as exc:
            raise CommandError(f'Carbon Mapper: {exc}')
        if not rows:
            raise CommandError('Carbon Mapper returned no sources; nothing changed.')
        report = carbonmapper.apply(rows)
        for line in report.lines():
            self.stdout.write(line)

        if options['no_plumes']:
            return
        try:
            items = carbonmapper.fetch_all_plumes()
        except requests.RequestException as exc:
            raise CommandError(f'Carbon Mapper plumes: {exc}')
        if not items:
            raise CommandError('Carbon Mapper returned no plumes; stored plumes unchanged.')
        plume_report = carbonmapper.apply_plumes(items)
        for line in plume_report.lines():
            self.stdout.write(line)
