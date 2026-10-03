import json
import tempfile

import requests
from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import stats
from camp.apps.emissions.importers import contable
from camp.apps.emissions.models import SourceImport


class Command(BaseCommand):
    help = "Import OEHHA health values from CARB's Consolidated Table PDF and recompute the toxic pollutant weights."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--path', help='A downloaded contable.pdf')
        group.add_argument('--url', nargs='?', const=contable.CONTABLE_URL, help=f'Download it (default: {contable.CONTABLE_URL})')
        parser.add_argument('--dump', help='Write the parsed rows as JSON to this path and change nothing')

    def handle(self, *args, **options):
        path = options['path']
        if not path:
            self.stdout.write(f"Downloading {options['url']}")
            response = requests.get(options['url'], timeout=60, headers={'User-Agent': 'Mozilla/5.0 (SJVAir importer)'})
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(response.content)
                path = tmp.name
        rows, date = contable.parse(path)
        if not rows:
            raise CommandError('No health-value rows parsed; has the table layout changed?')
        self.stdout.write(f'Parsed {len(rows):,} rows; table dated {date or "unknown"}')
        if options['dump']:
            with open(options['dump'], 'w') as handle:
                json.dump({'date': date.isoformat() if date else None, 'rows': rows}, handle, indent=1)
            self.stdout.write(f"Wrote {options['dump']}")
            return
        result = contable.apply(rows, date)
        SourceImport.objects.create(source='contable', version=date.isoformat() if date else '', data_through=date,
                                    notes={'rows': len(rows), **result})
        stats.clear_caches()
        self.stdout.write(f"{result['created']} pollutants created, {result['updated']} updated")
