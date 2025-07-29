from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        Region.objects.filter(type__in=[Region.Type.STATE_SENATE]).delete()

        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan('senate-districts')
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                external_id = f"sd-{row['GEOID']}"
                region = Region.objects.create(
                    name=row['SenateDist'],
                    slug=external_id,
                    type=Region.Type.STATE_ASSEMBLY,
                    external_id=external_id,
                    geometry=to_multipolygon(row.geometry),
                    metadata={}
                )
                self.stdout.write(f'Imported: {region.name}')
