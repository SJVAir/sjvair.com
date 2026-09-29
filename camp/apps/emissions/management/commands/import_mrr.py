import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import mrr, stats
from camp.apps.emissions.models import SourceImport


class Command(BaseCommand):
    help = (
        "Import CARB's Mandatory GHG Reporting workbook for one year: the Valley's emitters (by ZIP), "
        'emitter CO2e only, per-gas CH4 and N2O, matched to facilities. Idempotent. CARB changes the URL '
        'each November: pass --url <new file> for a new year.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Data year (the sheet names carry it)')
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--path', help='A locally downloaded MRR XLSX')
        source.add_argument('--url', nargs='?', const=mrr.URL, help=f'URL to download (default: {mrr.URL})')
        parser.add_argument('--report', action='store_true', help='After importing, print the largest emitters and their match for crosswalk curation')

    def handle(self, *args, **options):
        if options['path']:
            self.run(options['path'], options)
            return
        url = options['url'] or mrr.URL
        self.stdout.write(f'Downloading {url}')
        path = mrr.download(url)
        try:
            self.run(path, options)
        finally:
            os.unlink(path)

    def run(self, path, options):
        year = options['year']
        try:
            rows, gases = mrr.read(path, year)
        except mrr.MRRFormatError as err:
            raise CommandError(str(err))
        counts = mrr.apply(rows, gases, year)
        SourceImport.objects.create(
            source='mrr', version=str(year), data_through=date(year, 12, 31),
            notes={key: counts[key] for key in ('kept', 'outside', 'no_emitter', 'auto', 'crosswalk', 'unmatched', 'basin', 'deleted')},
        )
        stats.clear_caches()
        self.stdout.write(
            f'{len(rows)} reporters in the file: {counts["kept"]} emitters kept, {counts["outside"]} outside the Valley, '
            f'{counts["no_emitter"]} with no emitter CO2e. Matched {counts["auto"]} by name and ZIP, {counts["crosswalk"]} by crosswalk; '
            f'{counts["unmatched"]} unmatched ({counts["basin"]} basin-wide); {counts["deleted"]} deleted.'
        )
        if options['report']:
            self.stdout.write('\n'.join(mrr.audit(year)))
