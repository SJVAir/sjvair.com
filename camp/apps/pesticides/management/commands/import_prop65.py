import csv
import io

from django.core.management.base import BaseCommand

from camp.apps.pesticides.models import Chemical

# Download manually from: https://oehha.ca.gov/proposition-65/proposition-65-list
# The site uses JavaScript bot-protection that blocks server-side requests.

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
        parser.add_argument(
            '--path',
            required=True,
            help='Path to locally downloaded Prop 65 CSV file',
        )

    def handle(self, *args, **options):
        data = self._load(options['path'])
        cas_categories, name_categories = self._parse(data)
        self._apply(cas_categories, name_categories)

    def _load(self, path):
        with open(path, encoding='latin-1') as f:
            lines = f.readlines()
        # Skip the preamble rows; find the real header line
        for i, line in enumerate(lines):
            if line.startswith('Chemical,'):
                return ''.join(lines[i:])
        raise ValueError('Could not find header row in Prop 65 CSV')

    def _parse(self, data):
        cas_categories = {}
        name_categories = {}
        for row in csv.DictReader(io.StringIO(data)):
            cas = (row.get('CAS No.') or '').strip()
            name = (row.get('Chemical') or '').strip().upper()
            categories = set()
            for toxicity in (row.get('Type of Toxicity') or '').split(','):
                category = TOXICITY_MAP.get(toxicity.strip().lower())
                if category:
                    categories.add(category)
            if not categories:
                continue
            if cas and cas.upper() != 'N/A':
                cas_categories.setdefault(cas, set()).update(categories)
            if name:
                name_categories.setdefault(name, set()).update(categories)
        self.stdout.write(f'Parsed {len(cas_categories):,} CAS numbers from Prop 65 list')
        return cas_categories, name_categories

    def _apply(self, cas_categories, name_categories):
        updated = cas_matched = name_matched = 0
        for chemical in Chemical.objects.all():
            if chemical.cas_number:
                new_cats = cas_categories.get(chemical.cas_number)
            else:
                new_cats = name_categories.get(chemical.name.upper())
            if new_cats is None:
                continue
            if chemical.cas_number:
                cas_matched += 1
            else:
                name_matched += 1
            to_add = new_cats - set(chemical.categories)
            if to_add:
                chemical.categories = sorted(set(chemical.categories) | to_add)
                chemical.save(update_fields=['categories', 'modified'])
                updated += 1
        self.stdout.write(
            f'Matched {cas_matched:,} by CAS, {name_matched:,} by name, updated {updated:,}'
        )
