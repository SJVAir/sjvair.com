from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from camp.apps.regions.forecast_zones import derive_forecast_zones
from camp.apps.regions.models import Region

SVG_PATH = 'datafiles/sjvapcd-forecast-areas.svg'

# Not from any official published dataset -- keep the version tag tied to
# when this SVG was captured, so re-running after a fresher capture creates
# a new Boundary version rather than silently overwriting.
GEOMETRY_VERSION = '2026-07-12-svg'

ZONES = [
    {
        'key': 'kern_airbasin',
        'name': 'Kern (SJV Air Basin portion)',
        'external_id': 'sjvapcd-kern-airbasin',
        'metadata': {
            'source': 'SJVAPCD daily forecast map SVG',
            'derivation': 'Real Kern County boundary intersected with the SVG-derived forecast zone shape.',
        },
    },
    {
        'key': 'tulare_valley',
        'name': 'Tulare (SJV Valley portion)',
        'external_id': 'sjvapcd-tulare-valley',
        'metadata': {
            'source': 'SJVAPCD daily forecast map SVG',
            'derivation': 'Real Tulare County boundary intersected with the SVG-derived forecast zone shape.',
        },
    },
    {
        'key': 'sequoia',
        'name': 'Sequoia National Park and Forest',
        'external_id': 'sjvapcd-sequoia',
        'metadata': {
            'source': 'SJVAPCD daily forecast map SVG',
            'derivation': 'Real Tulare County boundary minus the Tulare (SJV Valley portion) zone -- '
                          'verified to overlap ~100% of the SVG-derived Sequoia shape and ~0% of the '
                          'portion excluded from Kern, i.e. carved entirely from Tulare, not Kern.',
        },
    },
]


class Command(BaseCommand):
    help = (
        'Derives lat/lon geometry for the 3 SJVAPCD forecast zones that don\'t map 1:1 to an '
        'existing county Region (Kern SJV Air Basin portion, Tulare valley portion, Sequoia '
        'National Park and Forest), from datafiles/sjvapcd-forecast-areas.svg, and imports them '
        'as Region(type=CUSTOM) + Boundary records.'
    )

    def handle(self, *args, **options):
        self.stdout.write(f'Deriving forecast zone geometry from {SVG_PATH}...')
        try:
            result = derive_forecast_zones(SVG_PATH)
        except RuntimeError as e:
            raise CommandError(str(e))

        self.stdout.write('Ground-control county fit (IoU against real boundaries):')
        for shape_id, score in result['gcp_iou'].items():
            self.stdout.write(f'  {shape_id}: {score:.4f}')

        for zone in ZONES:
            geometry = result[zone['key']]
            region, created = Region.objects.import_or_update(
                name=zone['name'],
                slug=slugify(zone['name']),
                type=Region.Type.CUSTOM,
                external_id=zone['external_id'],
                geometry=geometry,
                version=GEOMETRY_VERSION,
                metadata=zone['metadata'],
            )
            verb = 'Imported' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb}: {region.name} ({region.sqid})'))
