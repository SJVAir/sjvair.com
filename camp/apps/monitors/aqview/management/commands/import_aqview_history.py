import hashlib
import io
import sys

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.aqview.history import import_aqview_history


class Command(BaseCommand):
    help = (
        'Import historical AQview PM2.5 from CSVs (or zips) downloaded from '
        'https://aqview.arb.ca.gov/continuous-monitoring-data. Each file\'s '
        'range replaces the stored PM2.5 for its monitors; rows the provider '
        'invalidated are skipped. Idempotent. Pass - to read one file from '
        'stdin, e.g. `heroku run --no-tty -- python manage.py '
        'import_aqview_history - --sha256 <hash> < download.zip`.'
    )

    def add_arguments(self, parser):
        parser.add_argument('paths', nargs='+', help='Download-tool CSV or zip files, or - for stdin.')
        parser.add_argument(
            '--sha256',
            help='Expected SHA-256 of the file read from stdin; nothing is imported if it differs.',
        )

    def handle(self, *args, **options):
        paths = options['paths']
        if paths.count('-') > 1:
            raise CommandError('stdin (-) can only be read once.')

        sources = [self.read_stdin(options['sha256']) if path == '-' else path for path in paths]
        try:
            totals = import_aqview_history(sources, log=self.stdout.write)
        except FileNotFoundError as err:
            raise CommandError(str(err))

        self.stdout.write(self.style.SUCCESS(
            f'Done: {totals.get("raw", 0)} raw and {totals.get("cleaned", 0)} cleaned entries across '
            f'{totals.get("monitors", 0)} monitor ranges ({totals.get("invalid", 0)} invalidated rows skipped, '
            f'{totals.get("removed", 0)} old entries removed).'
        ))

    def read_stdin(self, expected):
        data = sys.stdin.buffer.read()
        digest = hashlib.sha256(data).hexdigest()
        self.stdout.write(f'Read {len(data)} bytes from stdin, sha256 {digest}')
        if not data:
            raise CommandError('Nothing was read from stdin.')
        if expected and expected.lower() != digest:
            raise CommandError(f'stdin sha256 {digest} does not match --sha256 {expected}; nothing imported.')
        return ('<stdin>', io.BytesIO(data))
