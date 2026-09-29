import os

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import compliance
from camp.apps.emissions.importers import icis


class Command(BaseCommand):
    help = (
        "Import EPA ICIS-Air (Clean Air Act compliance) for the covered counties: facilities, inspections, notices of "
        'violation, formal actions and high-priority violations, matched to CEIDARS facilities. Idempotent. '
        'Downloads the weekly bulk zip unless --path names a local copy.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A locally downloaded ICIS-AIR_downloads.zip')

    def handle(self, *args, **options):
        path = options['path']
        downloaded = path is None
        if downloaded:
            self.stdout.write(f'Downloading {icis.URL}')
            path = icis.download()
        try:
            try:
                data = icis.read(path)
            except icis.ICISFormatError as err:
                raise CommandError(str(err))
            report = icis.apply(data)
        finally:
            if downloaded:
                os.unlink(path)
        compliance.clear_caches()
        for line in report.lines():
            self.stdout.write(line)
