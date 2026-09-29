import os
import tempfile

import requests
from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import ddrdp

MIN_ROWS = 100


class Command(BaseCommand):
    help = (
        "Import CDFA's Dairy Digester Research and Development Program (DDRDP) project-level PDF into "
        'DigesterGrant rows: matches each grant to a Dairy by name and mailing city (falling back to a name '
        "that's unique Valley-wide, then ddrdp_crosswalk.CROSSWALK), replaces the table, and prints the "
        'projects it could not match, grouped by county, so the crosswalk can be extended. Manual -- CDFA '
        'updates the PDF a few times a year, so there is no periodic task; re-run this when it does. --path '
        'reads a saved PDF instead of downloading; --url (default the live CDFA PDF) downloads one first.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A saved DDRDP PDF to import instead of downloading')
        parser.add_argument(
            '--url', nargs='?', const=ddrdp.URL,
            help='Download the PDF from this URL first (default: the live CDFA URL)',
        )

    def handle(self, *args, **options):
        path = options['path']
        tmp_path = None
        if not path:
            url = options['url'] or ddrdp.URL
            try:
                response = requests.get(url, timeout=120)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f'DDRDP: could not download {url}: {exc}')
            handle_, tmp_path = tempfile.mkstemp(suffix='.pdf')
            with os.fdopen(handle_, 'wb') as fh:
                fh.write(response.content)
            path = tmp_path

        try:
            try:
                rows, version = ddrdp.parse(path)
            except ddrdp.DDRDPFormatError as exc:
                raise CommandError(f'DDRDP: {exc}')
        finally:
            if tmp_path:
                os.remove(tmp_path)

        if len(rows) < MIN_ROWS:
            raise CommandError(f'DDRDP: only {len(rows)} projects parsed (expected {MIN_ROWS}+); the PDF layout may have changed.')

        matched = ddrdp.match(rows)
        report = ddrdp.apply(matched, version)
        for line in report.lines():
            self.stdout.write(line)

        unmatched = [row for row in matched if not row['match_method']]
        if unmatched:
            self.stdout.write('')
            self.stdout.write('Unmatched (add to ddrdp_crosswalk.CROSSWALK):')
            by_county = {}
            for row in unmatched:
                by_county.setdefault(row.get('county') or 'Unknown', []).append(row)
            for county in sorted(by_county):
                self.stdout.write(f'  {county}:')
                for row in by_county[county]:
                    self.stdout.write(f"    {row['project_name']!r}, {row.get('city') or '?'}")
