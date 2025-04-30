from django.contrib.gis.db.models.functions import Distance
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from camp.apps.calibrations.models import CalibrationPair
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir

from decimal import Decimal


MAX_DISTANCE_FEET = 528


class Command(BaseCommand):
    help = 'Auto-create CalibrationPairs by linking AirNow and nearby PurpleAir monitors'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Print actions without saving')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        cutoff = Decimal(MAX_DISTANCE_FEET) / Decimal('5280')  # convert feet to miles

        created = 0
        skipped_distance = 0
        skipped_existing = 0
        inactive = 0

        airnow_queryset = AirNow.objects.get_active().exclude(reference_pairs__isnull=False)

        for airnow in airnow_queryset:
            # Skip if a pair already exists for this AirNow
            if CalibrationPair.objects.filter(reference=airnow).exists():
                skipped_existing += 1
                continue

            closest = (PurpleAir.objects.get_active()
                .exclude(colocated_pairs__isnull=False)
                .annotate(distance=Distance('position', airnow.position))
                .order_by('distance')
                .first())

            if not closest:
                if dry_run:
                    self.stdout.write(f'{airnow.name}: No nearby PurpleAir found.')
                continue

            if closest.distance.mi > float(cutoff):
                skipped_distance += 1
                if dry_run:
                    self.stdout.write(f'{airnow.name}: Closest PurpleAir > {MAX_DISTANCE_FEET} ft ({closest.distance.mi:.2f} mi)')
                continue

            if dry_run:
                self.stdout.write(f'{airnow.name}: Would pair with {closest.name} ({closest.distance.mi:.2f} mi)')
            else:
                CalibrationPair.objects.create(
                    reference=airnow,
                    colocated=closest,
                    entry_type='pm25',
                    is_enabled=True,
                    created=now()
                )
                self.stdout.write(self.style.SUCCESS(f'{airnow.name}: Paired with {closest.name} ({closest.distance.mi:.2f} mi)'))
                created += 1

        self.stdout.write(self.style.NOTICE(f"Done. Created: {created}, Existing: {skipped_existing}, Too far: {skipped_distance}"))
