import datetime

from django.core.management.base import BaseCommand

from camp.apps.emissions import locations, pmt
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region
from camp.utils import geocode

# A moved point is listed when it moves at least this far.
REPORT_METERS = 1000


class Command(BaseCommand):
    help = (
        "Re-choose every facility's point from CARB's Pollution Mapping Tool "
        "coordinates and a fresh Census street match (locations.choose_point: "
        "Census street match, then CARB, then the point it has). Safe to re-run; "
        "run it after import_ceidars."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would change; write nothing')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        markers, years = pmt.fetch_markers(range(pmt.FIRST_YEAR, datetime.date.today().year + 1))
        self.stdout.write(f'CARB marker files: {", ".join(map(str, years)) or "none"} ({len(markers)} facilities)')

        changed = []
        moved = []
        counts = {'census': 0, 'carb': 0, 'current': 0, 'none': 0}
        facilities = list(Facility.objects.select_related(None).select_related('air_district', 'county__boundary'))

        census = self.census_matches(facilities)
        areas = {}
        for facility in facilities:
            if facility.county_id not in areas:
                areas[facility.county_id] = locations.county_area(facility.county)
            carb = markers.get((facility.county_code, facility.air_district.external_id, facility.facid))
            point = locations.choose_point(
                facility.address or {},
                census=census.get(facility.pk),
                carb=carb,
                current=facility.point,
                area=areas[facility.county_id],
            )
            if point is None:
                counts['none'] += 1
            elif point is census.get(facility.pk):
                counts['census'] += 1
            elif point is carb:
                counts['carb'] += 1
            else:
                counts['current'] += 1

            if not self.same(point, facility.point):
                distance = self.distance(facility.point, point)
                if distance is None or distance >= REPORT_METERS:
                    moved.append((facility, distance))
                facility.point = point
                changed.append(facility)

        for facility, distance in sorted(moved, key=lambda row: -(row[1] or 0)):
            how_far = 'new point' if distance is None else f'{distance / 1000:.1f} km'
            self.stdout.write(f'  {facility.name} ({facility.get_county()}): {how_far}')
        self.stdout.write(
            'Points from: {census} Census street matches, {carb} CARB, {current} kept, {none} none.'.format(**counts)
        )
        if not dry_run and changed:
            Facility.objects.bulk_update(changed, ['point'], batch_size=1000)
        verb = 'Would update' if dry_run else 'Updated'
        self.stdout.write(f'{verb} {len(changed)} facility points ({len(moved)} moved {REPORT_METERS // 1000} km or more, or new).')

    def census_matches(self, facilities):
        """{facility pk: Point} for the facilities whose street address Census matches."""
        addresses = [
            dict(facility.address, state='CA', pk=facility.pk)
            for facility in facilities
            if locations.is_geocodable(facility.address or {})
        ]
        if addresses:
            self.stdout.write(f'Census: matching {len(addresses)} street addresses...')
        return {address['pk']: point for address, point in geocode.census_batch(addresses) if point is not None}

    @staticmethod
    def same(a, b):
        if a is None or b is None:
            return a is b
        return a.equals_exact(b, 1e-7)

    @staticmethod
    def distance(a, b):
        """Meters between two points (California Albers); None when either is missing."""
        if a is None or b is None:
            return None
        return a.transform(3310, clone=True).distance(b.transform(3310, clone=True))
