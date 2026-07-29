from decimal import Decimal

from django.core.management.base import BaseCommand

from camp.apps.entries.models import Pressure
from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir


class Command(BaseCommand):
    help = (
        'One-time repair for PurpleAir Pressure RAW entries created by the old '
        'migrate_legacy_entry path, which copied legacy pressure (hPa) directly '
        'into `value` (mmHg) with no unit conversion. Recomputes each entry from '
        'its legacy source and updates in place if the value is wrong.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
            help='Report how many entries would be corrected without saving changes')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        corrected = 0
        checked = 0

        queryset = Pressure.objects.filter(
            monitor__in=PurpleAir.objects.all(), stage=Pressure.Stage.RAW,
        ).iterator(chunk_size=1000)

        for entry in queryset:
            checked += 1
            legacy = (Entry.objects
                .filter(monitor_id=entry.monitor_id, timestamp=entry.timestamp, pressure__isnull=False)
                .first())
            if legacy is None:
                continue

            correct_value = (legacy.pressure / Decimal('1.33322')).quantize(Decimal('0.01'))
            if entry.value == correct_value:
                continue

            corrected += 1
            if not dry_run:
                entry.value = correct_value
                entry.save(update_fields=['value'])

        verb = 'Would correct' if dry_run else 'Corrected'
        self.stdout.write(self.style.SUCCESS(f'{verb} {corrected} of {checked} checked entries.'))
