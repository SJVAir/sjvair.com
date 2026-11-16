from django.core.management.base import BaseCommand

from camp.apps.emissions import audit, stats
from camp.apps.emissions.models import Facility


class Command(BaseCommand):
    help = (
        "Clear facility points that can't be right: ones geocoded outside the "
        "facility's county, and ones geocoded from a non-address (\"various "
        "locations\", oil-field names). The facilities stay; they just drop off the map."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Count and list what would change; write nothing')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        cleared = audit.points_to_clear()

        for facility in cleared:
            self.stdout.write(f'  {facility.name} ({facility.get_county()}): {facility.address}')
        if not dry_run and cleared:
            Facility.objects.filter(pk__in=[facility.pk for facility in cleared]).update(point=None, point_source='')
            stats.clear_caches()
        verb = 'Would clear' if dry_run else 'Cleared'
        self.stdout.write(f'{verb} {len(cleared)} facility points.')
