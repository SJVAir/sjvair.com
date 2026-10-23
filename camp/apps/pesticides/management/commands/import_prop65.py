import csv
import io
import re

from django.core.management.base import BaseCommand

from camp.apps.pesticides import rollup
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

# Prop 65's group listings carry no CAS number, so CAS matching misses every
# chemical they cover. Each maps the listing's name in the CSV to a regex
# over CDPR's chemical name; the categories still come from the CSV.
GROUP_LISTINGS = {
    'ARSENIC (INORGANIC ARSENIC COMPOUNDS)': r'ARSEN(IC|ATE|ITE|IDE)',
    'ARSENIC (INORGANIC OXIDES)': r'ARSENIC (TRI|PENT)OXIDE',
    'CADMIUM AND CADMIUM COMPOUNDS': r'CADMIUM',
    'CHROMIUM (HEXAVALENT COMPOUNDS)': r'CHROMATE|CHROMIC ACID|CHROMIUM TRIOXIDE',
    'LEAD AND LEAD COMPOUNDS': r'\bLEAD\b',
    'LINDANE AND OTHER HEXACHLOROCYCLOHEXANE ISOMERS': r'\bLINDANE\b|\bBHC\b|HEXACHLOROCYCLOHEXANE',
    'MERCURY AND MERCURY COMPOUNDS': r'MERCUR',
    'NICKEL COMPOUNDS': r'NICKEL',
}


class Command(BaseCommand):
    help = 'Import Prop 65 chemical classifications from OEHHA.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            required=True,
            help='Path to locally downloaded Prop 65 CSV file',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        data = self._load(options['path'])
        cas_categories, name_categories = self._parse(data)
        self._apply(cas_categories, name_categories, dry_run=options['dry_run'])

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
            # A cell can hold several CAS numbers ("12054-48-7; 12125-56-3").
            for number in re.split(r'[;,\s]+', cas):
                if re.fullmatch(r'\d+-\d+-\d', number):
                    cas_categories.setdefault(number, set()).update(categories)
            if name:
                name_categories.setdefault(name, set()).update(categories)
        self.stdout.write(f'Parsed {len(cas_categories):,} CAS numbers from Prop 65 list')
        return cas_categories, name_categories

    def _apply(self, cas_categories, name_categories, dry_run=False):
        # The Prop 65 categories come from this list alone: a chemical it
        # doesn't list loses them (import_carbtac once set CARCINOGEN from
        # CARB's cancer potencies, which aren't Prop 65 listings).
        prop65 = Chemical.PROP65_CATEGORIES
        groups = [(re.compile(pattern), name_categories[name]) for name, pattern in GROUP_LISTINGS.items() if name in name_categories]
        missing = sorted(set(GROUP_LISTINGS) - set(name_categories))
        if missing:
            self.stdout.write(f'  Group listings not in this CSV (renamed?): {", ".join(missing)}')
        cas_matched = name_matched = group_matched = 0
        updated, cleared = [], []
        for chemical in Chemical.objects.all():
            if chemical.cas_number:
                listed = cas_categories.get(chemical.cas_number)
            else:
                listed = name_categories.get(chemical.name.upper())
            if listed is not None:
                if chemical.cas_number:
                    cas_matched += 1
                else:
                    name_matched += 1
            in_group = [categories for pattern, categories in groups if pattern.search(chemical.name.upper())]
            if in_group:
                group_matched += 1
                listed = set(listed or ()).union(*in_group)
            current = set(chemical.categories or [])
            new = (current - prop65) | (listed or set())
            if new == current:
                continue
            (updated if listed else cleared).append(chemical.name)
            if not dry_run:
                chemical.categories = sorted(new)
                chemical.save(update_fields=['categories', 'modified'])
        self.stdout.write(f'Matched {cas_matched:,} by CAS, {name_matched:,} by name, {group_matched:,} by a group listing')
        self.stdout.write(f'  Updated {len(updated):,}; cleared Prop 65 categories from {len(cleared):,} it does not list')
        for name in cleared[:25]:
            self.stdout.write(f'    {name}')
        if len(cleared) > 25:
            self.stdout.write(f'    ... and {len(cleared) - 25:,} more')
        if dry_run:
            self.stdout.write('Dry run: nothing written.')
        else:
            self.stdout.write(rollup.REBUILD_REMINDER)
