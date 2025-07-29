from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan('senate-districts')
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                external_id = f"sd-{row['GEOID']}"
                region, created = Region.objects.update_or_create(
                    external_id=external_id,
                    type=Region.Type.STATE_ASSEMBLY,
                    defaults={
                        'name': row['SenateDist'],
                        'slug': external_id,
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {}
                    }
                )
                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
