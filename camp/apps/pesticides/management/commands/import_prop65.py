import csv
import io

import requests
from django.core.management.base import BaseCommand

from camp.apps.pesticides.models import Chemical

# Download from: https://oehha.ca.gov/proposition-65/proposition-65-list
PROP65_URL = 'https://oehha.ca.gov/media/downloads/proposition-65/p65list.csv'

TOXICITY_MAP = {
    'cancer': Chemical.Category.CARCINOGEN,
    'developmental': Chemical.Category.DEVELOPMENTAL_TOXIN,
    'female': Chemical.Category.REPRODUCTIVE_TOXIN,
    'male': Chemical.Category.REPRODUCTIVE_TOXIN,
    'reproductive': Chemical.Category.REPRODUCTIVE_TOXIN,
}


class Command(BaseCommand):
    help = 'Import Prop 65 chemical classifications from OEHHA.'

    def add_arguments(self, parser):
        parser.add_argument('--url', default=PROP65_URL, help='URL to Prop 65 CSV')
        parser.add_argument('--path', help='Path to local Prop 65 CSV file')

    def handle(self, *args, **options):
        data = self._load(options)
        cas_categories = self._parse(data)
        self._apply(cas_categories)

    def _load(self, options):
        if options.get('path'):
            with open(options['path'], encoding='utf-8-sig') as f:
                return f.read()
        url = options['url']
        self.stdout.write(f'Downloading {url}')
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.text

    def _parse(self, data):
        cas_categories = {}
        for row in csv.DictReader(io.StringIO(data)):
            cas = (row.get('CAS No.') or '').strip()
            if not cas or cas.upper() == 'N/A':
                continue
            toxicity = (row.get('Type of Toxicity') or '').strip().lower()
            category = TOXICITY_MAP.get(toxicity)
            if not category:
                continue
            cas_categories.setdefault(cas, set()).add(category)
        self.stdout.write(f'Parsed {len(cas_categories):,} CAS numbers from Prop 65 list')
        return cas_categories

    def _apply(self, cas_categories):
        updated = matched = 0
        for chemical in Chemical.objects.exclude(cas_number=''):
            new_cats = cas_categories.get(chemical.cas_number)
            if new_cats is None:
                continue
            matched += 1
            to_add = new_cats - set(chemical.categories)
            if to_add:
                chemical.categories = sorted(set(chemical.categories) | to_add)
                chemical.save(update_fields=['categories', 'modified'])
                updated += 1
        self.stdout.write(f'Matched {matched:,} chemicals, updated {updated:,}')
