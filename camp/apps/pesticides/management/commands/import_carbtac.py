import re
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides import rollup
from camp.apps.pesticides.models import Chemical

# CARB's TAC list (17 CCR 93000 and 93001), curated in the repo: CARB
# publishes it as regulation text with names only. The file says where each
# part comes from. CARB's health-values table (contable.pdf) is not the list:
# it covers many substances that aren't TACs.
DEFAULT_PATH = Path(settings.BASE_DIR) / 'datafiles' / 'toxic-air-contaminants.yaml'


def listings(data):
    """A function (chemical) -> the TAC listing that covers it, or None: by its CAS number, else by a by_name pattern over its name."""
    by_cas = {entry['cas']: entry['name'] for entry in data.get('substances') or []}
    patterns = [(re.compile(entry['pattern']), entry['name']) for entry in data.get('by_name') or []]

    def listing(chemical):
        if chemical.cas_number in by_cas:
            return by_cas[chemical.cas_number]
        name = chemical.name.strip().upper()
        for pattern, label in patterns:
            if pattern.search(name):
                return label
        return None

    return listing


class Command(BaseCommand):
    help = (
        "Tag chemicals on CARB's toxic air contaminant list (17 CCR 93000/93001) and untag the rest. "
        'Reads the curated list in datafiles/; nothing to download.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=str(DEFAULT_PATH),
            help=f'Path to the TAC list YAML (default: {DEFAULT_PATH})',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        data = self._load(options['path'])
        self._apply(listings(data), dry_run=options['dry_run'])

    def _load(self, path):
        try:
            data = yaml.safe_load(Path(path).read_text())
        except FileNotFoundError:
            raise CommandError(f'No TAC list at {path}')
        if not (data or {}).get('substances'):
            raise CommandError(f'{path} has no substances')
        self.stdout.write(f'Loaded {len(data["substances"]):,} substances from {path}')
        return data

    def _apply(self, listing, dry_run=False):
        category = Chemical.Category.TOXIC_AIR_CONTAMINANT
        matched = 0
        added, removed = [], []
        for chemical in Chemical.objects.all():
            categories = set(chemical.categories or [])
            label = listing(chemical)
            if label:
                matched += 1
                if category in categories:
                    continue
                added.append(f'{chemical.name} ({label})')
                categories.add(category)
            elif category in categories:
                # Tagged by an earlier import that read the wrong list.
                removed.append(chemical.name)
                categories.discard(category)
            else:
                continue
            if not dry_run:
                chemical.categories = sorted(categories)
                chemical.save(update_fields=['categories', 'modified'])

        self.stdout.write(f'{matched:,} chemicals are on the list')
        for label, names in (('Added', added), ('Removed', removed)):
            self.stdout.write(f'  {label} TOXIC_AIR_CONTAMINANT: {len(names):,}')
            for name in names[:25]:
                self.stdout.write(f'    {name}')
            if len(names) > 25:
                self.stdout.write(f'    ... and {len(names) - 25:,} more')
        if dry_run:
            self.stdout.write('Dry run: nothing written.')
        else:
            self.stdout.write(rollup.REBUILD_REMINDER)
