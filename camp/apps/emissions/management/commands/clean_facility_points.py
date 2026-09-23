from django.core.management.base import BaseCommand

from camp.apps.emissions import locations
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region


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
        cleared = []

        for county in Region.objects.counties().select_related('boundary').order_by('name'):
            area = locations.county_area(county)
            facilities = Facility.objects.filter(county=county, point__isnull=False)
            outside = facilities.exclude(point__within=area) if area is not None else facilities.none()
            cleared.extend(outside)
            cleared.extend(
                facility for facility in facilities.exclude(pk__in=outside.values('pk'))
                if not locations.is_geocodable(facility.address)
            )

        for facility in cleared:
            self.stdout.write(f'  {facility.name} ({facility.get_county()}): {facility.address}')
        if not dry_run and cleared:
            Facility.objects.filter(pk__in=[facility.pk for facility in cleared]).update(point=None)
        verb = 'Would clear' if dry_run else 'Cleared'
        self.stdout.write(f'{verb} {len(cleared)} facility points.')
