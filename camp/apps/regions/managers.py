from typing import Optional

from django.db import models

from camp.apps.regions.querysets import RegionQuerySet
from camp.utils.gis import to_multipolygon


class RegionManager(models.Manager.from_queryset(RegionQuerySet)):
    def import_or_update(cls,
        name: str,
        slug: str,
        type: 'Region.Type',
        external_id: str,
        geometry,
        version: str,
        metadata: Optional[dict] = None,
    ) -> 'Region':
        from .models import Region, Boundary
        region, created = Region.objects.update_or_create(
            external_id=external_id,
            type=type,
            defaults={
                'name': name,
                'slug': slug,
            }
        )

        boundary, _ = Boundary.objects.update_or_create(
            region_id=region.pk,
            version=version,
            defaults={
                'geometry': to_multipolygon(geometry),
                'metadata': metadata or {}
            }
        )

        region.boundary = boundary
        region.save(update_fields=['boundary'])
        return region, created
