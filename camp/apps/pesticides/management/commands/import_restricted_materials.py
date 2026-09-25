import yaml
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides.models import Chemical

# Unlike Prop 65 and the CARB table, there is nothing to download: CDPR's
# restricted materials page links no file, and the list itself is regulation
# text (3 CCR 6400(e)) naming active ingredients. It's curated in the repo
# instead, with each regulation entry mapped to the PUR chemical names it
# covers -- CDPR splits several of them into salts and esters.
DEFAULT_PATH = Path(settings.BASE_DIR) / 'datafiles' / 'restricted-materials.yaml'


class Command(BaseCommand):
    help = 'Apply California restricted material (3 CCR 6400) classifications to chemicals.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=str(DEFAULT_PATH),
            help=f'Path to the restricted materials YAML (default: {DEFAULT_PATH})',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        entries = self._load(options['path'])
        self._apply(entries, dry_run=options['dry_run'])

    def _load(self, path):
        try:
            data = yaml.safe_load(Path(path).read_text())
        except FileNotFoundError:
            raise CommandError(f'No restricted materials file at {path}')
        entries = (data or {}).get('entries')
        if not entries:
            raise CommandError(f'{path} has no entries')
        self.stdout.write(f'Loaded {len(entries):,} regulation entries from {path}')
        return entries

    def _apply(self, entries, dry_run=False):
        # {upper chemical name: the regulation entry that names it}
        wanted = {}
        for entry in entries:
            for name in entry.get('chemicals') or []:
                wanted[name.strip().upper()] = entry.get('regulation', '')

        category = Chemical.Category.CALIFORNIA_RESTRICTED
        matched = added = already = 0
        seen = set()
        for chemical in Chemical.objects.all():
            key = chemical.name.strip().upper()
            if key not in wanted:
                continue
            matched += 1
            seen.add(key)
            categories = set(chemical.categories or [])
            if category in categories:
                already += 1
                continue
            added += 1
            if not dry_run:
                chemical.categories = sorted(categories | {category})
                chemical.save(update_fields=['categories', 'modified'])

        self.stdout.write(f'Matched {matched:,} chemicals by name')
        self.stdout.write(f'  {added:,} newly classified, {already:,} already were')

        # A name in the file that matches nothing means the file and the
        # chemical table have drifted -- a rename, or a year not yet
        # imported. Silence there is how the old RESTRICTED.txt lookup went
        # unnoticed for so long.
        missing = sorted(set(wanted) - seen)
        if missing:
            self.stdout.write(self.style.WARNING(
                f'  {len(missing):,} names in the file matched no chemical:'))
            for name in missing:
                self.stdout.write(f'    {name}  ({wanted[name]})')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: nothing written.'))
