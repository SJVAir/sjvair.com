import os
import tempfile

import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import cadd, dairies


class Command(BaseCommand):
    help = (
        "Import CARB's California Dairy & Livestock Database (CADD): the covered counties' dairies, "
        'their herds by year and their anaerobic digesters. Idempotent. CARB changes the URL with '
        'each version: pass --url <new file> --cadd-version <version> for a new one.'
    )

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument('--path', help='A locally downloaded CADD XLSX')
        source.add_argument('--url', nargs='?', const=cadd.URL, help=f'URL to download (default: {cadd.URL})')
        # Not --version: every management command already has that.
        parser.add_argument('--cadd-version', default=cadd.VERSION, help=f'The file\'s CADD version (default: {cadd.VERSION})')

    def handle(self, *args, **options):
        if options['path']:
            self.run(options['path'], options['cadd_version'])
            return
        url = options['url'] or cadd.URL
        self.stdout.write(f'Downloading {url}')
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp.write(response.content)
        try:
            self.run(tmp.name, options['cadd_version'])
        finally:
            os.unlink(tmp.name)

    def run(self, path, version):
        try:
            sheets = cadd.read(path)
        except cadd.CADDFormatError as err:
            raise CommandError(str(err))
        report = cadd.apply(sheets, version)
        dairies.clear_caches()
        for line in report.lines():
            self.stdout.write(line)
