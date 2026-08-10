from django.core.management.base import BaseCommand

from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022


def _count_with_descendants(entry):
    count = 1
    for child in entry.derived_entries.all():
        count += _count_with_descendants(child)
    return count


def _delete_with_descendants(entry):
    count = 0
    for child in list(entry.derived_entries.all()):
        count += _delete_with_descendants(child)
    count += 1
    entry.delete()
    return count


class Command(BaseCommand):
    help = (
        'One-time cleanup: removes PM25 RAW entries (and anything derived from '
        'them) carrying the 99999 bad-data sentinel value for BAM monitors. '
        'Real-time ingest no longer creates these going forward (see '
        'BAM1022.create_entry), but rows created before that fix -- via '
        'real-time ingest or the old, now-superseded migrate_legacy_entry path '
        '-- may still exist.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
            help='Report how many entries would be removed without deleting them')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        removed = 0

        raw_ids = list(PM25.objects.filter(
            monitor__in=BAM1022.objects.all(), stage=PM25.Stage.RAW, value=99999,
        ).values_list('pk', flat=True))

        for pk in raw_ids:
            entry = PM25.objects.filter(pk=pk).first()
            if entry is None:
                continue  # already removed as a descendant of an earlier entry in this run
            if dry_run:
                removed += _count_with_descendants(entry)
            else:
                removed += _delete_with_descendants(entry)

        verb = 'Would remove' if dry_run else 'Removed'
        self.stdout.write(self.style.SUCCESS(f'{verb} {removed} entries ({len(raw_ids)} RAW sentinel rows found).'))
