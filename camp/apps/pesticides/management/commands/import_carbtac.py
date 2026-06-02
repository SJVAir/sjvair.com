import re
import tempfile

import pdfplumber
import requests
from django.core.management.base import BaseCommand

from camp.apps.pesticides.models import Chemical

# URL changes when CARB updates the table; re-check periodically.
CARB_TAC_URL = 'https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable09252025.pdf'

CAS_RE = re.compile(r'^\d+-\d+-\d+$')

COL_NAME = 0
COL_CAS = 1
CANCER_COLS = (10, 11, 13)  # Inhalation Unit Risk, Cancer Potency Factor, Oral Slope Factor


def _cell(value):
    """Strip whitespace and trailing TAC marker from a cell value."""
    s = (value or '').strip()
    if s.endswith('TAC'):
        s = s[:-3].strip()
    return s


class Command(BaseCommand):
    help = 'Import CARB Toxic Air Contaminant classifications from the consolidated health values PDF.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--path', help='Path to a locally downloaded CARB TAC PDF')
        group.add_argument(
            '--url',
            nargs='?',
            const=CARB_TAC_URL,
            help=f'URL to download (default: {CARB_TAC_URL})',
        )

    def handle(self, *args, **options):
        if options['path']:
            self._run(options['path'])
        else:
            url = options['url'] or CARB_TAC_URL
            self.stdout.write(f'Downloading {url}')
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            self._run(tmp_path)

    def _run(self, path):
        rows = self._extract(path)
        self.stdout.write(f'Extracted {len(rows):,} rows from PDF')
        self._apply(rows)

    def _extract(self, path):
        rows = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue
                for row in table:
                    if not row or len(row) < 14:
                        continue
                    cas = _cell(row[COL_CAS])
                    if not CAS_RE.match(cas):
                        continue
                    rows.append(row)
        return rows

    def _apply(self, rows):
        cas_carcinogen = {}
        for row in rows:
            cas = _cell(row[COL_CAS])
            is_carcinogen = any(_cell(row[col]) for col in CANCER_COLS if col < len(row))
            cas_carcinogen[cas] = cas_carcinogen.get(cas, False) or is_carcinogen

        self.stdout.write(f'  {len(cas_carcinogen):,} unique CAS numbers')
        self.stdout.write(f'  {sum(cas_carcinogen.values()):,} with cancer data')

        matched = tac_added = carcinogen_added = 0
        for chemical in Chemical.objects.exclude(cas_number=''):
            is_carcinogen = cas_carcinogen.get(chemical.cas_number)
            if is_carcinogen is None:
                continue
            matched += 1
            cats = set(chemical.categories)
            to_add = set()
            if Chemical.Category.TOXIC_AIR_CONTAMINANT not in cats:
                to_add.add(Chemical.Category.TOXIC_AIR_CONTAMINANT)
                tac_added += 1
            if is_carcinogen and Chemical.Category.CARCINOGEN not in cats:
                to_add.add(Chemical.Category.CARCINOGEN)
                carcinogen_added += 1
            if to_add:
                chemical.categories = sorted(cats | to_add)
                chemical.save(update_fields=['categories', 'modified'])

        self.stdout.write(f'Matched {matched:,} chemicals by CAS number')
        self.stdout.write(f'  Added TOXIC_AIR_CONTAMINANT to {tac_added:,}')
        self.stdout.write(f'  Added CARCINOGEN to {carcinogen_added:,}')
