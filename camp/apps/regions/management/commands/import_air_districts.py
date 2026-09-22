from django.contrib.gis.db.models import Union
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from camp.apps.regions import air_districts
from camp.apps.regions.models import Region

# The layer has no published version; tie the Boundary version to when it
# was fetched, so a later refresh adds a version instead of overwriting.
GEOMETRY_VERSION = '2026-09-22'

# A district counts as covered when at least this share of its area lies in
# the covered counties. Districts that merely share a border with them only
# overlap by slivers where the two sources' lines disagree.
MIN_COVERED_SHARE = 0.01


class Command(BaseCommand):
    help = (
        'Import the CARB air districts that cover the counties in '
        'settings.SJVAIR_COUNTIES as Region(type=air_district) + Boundary records.'
    )

    def handle(self, *args, **options):
        coverage = Region.objects.counties().aggregate(area=Union('boundary__geometry'))['area']
        if coverage is None:
            raise CommandError('No county Regions with boundaries are loaded; run import_counties first.')

        directory = air_districts.load_directory()
        self.stdout.write('Fetching CARB air district boundaries...')
        districts = air_districts.group_by_code(air_districts.fetch_features())

        imported = 0
        for code, district in sorted(districts.items()):
            geometry = district['geometry']
            share = geometry.intersection(coverage).area / geometry.area if geometry.area else 0
            if share < MIN_COVERED_SHARE:
                continue

            entry = directory.get(code) or {}
            name = entry.get('name') or air_districts.title_case(district['name'])
            metadata = {
                'code': code,
                'arcgis_name': district['name'],
                **{field: entry.get(field, '') for field in air_districts.DIRECTORY_FIELDS},
            }
            region, created = Region.objects.import_or_update(
                name=name,
                slug=slugify(name),
                type=Region.Type.AIR_DISTRICT,
                external_id=code,
                geometry=geometry,
                version=GEOMETRY_VERSION,
                metadata=metadata,
            )
            imported += 1
            verb = 'Imported' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb}: {region.name} ({code})'))

        self.stdout.write(f'{imported} air districts cover the configured counties.')
