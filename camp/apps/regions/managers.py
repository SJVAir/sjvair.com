from typing import Optional

from django.contrib.gis.db import models
from django.contrib.gis.geos.geometry import GEOSGeometry
from django.db.models import F, Func, Value
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import FloatField

from camp.apps.regions.querysets import RegionQuerySet
from camp.utils.gis import to_multipolygon


class RegionManager(models.Manager.from_queryset(RegionQuerySet)):
    def counties(self):
        return self.filter(type=self.model.Type.COUNTY)

    def get_county_region(self, obj):
        return self.get_containing_region(obj, self.model.Type.COUNTY)

    def get_containing_region(self, obj, region_type) -> 'Region | None':
        """
        Returns the county Region that this Region is located in,
        using covers() first, then intersects() with largest overlap.
        """
        from camp.apps.regions.models import Region, Boundary

        if isinstance(obj, GEOSGeometry):
            geometry = obj
        elif isinstance(obj, Boundary):
            geometry = obj.geometry
        elif isinstance(obj, Region):
            geometry = obj.boundary.geometry
        else:
            raise ValueError('Object type must be a geometry, Region, or Boundary.')

        # Quick win: try covers
        if county := self.model.objects.filter(
            type=region_type,
            boundary__geometry__covers=geometry,
        ).first():
            return county

        # Fallback: intersecting with max area of intersection
        geom_value = Func(
            Value(geometry.wkt),
            Value(geometry.srid),
            function='ST_GeomFromText',
            template='%(function)s(%(expressions)s)',
            output_field=models.GeometryField(srid=geometry.srid),
        )

        intersecting = self.model.objects.filter(
            type=region_type,
            boundary__geometry__intersects=geometry,
        ).annotate(
            overlap_area=ExpressionWrapper(
                Func(
                    F('boundary__geometry'),
                    geom_value,
                    function='ST_Area',
                    template='ST_Area(ST_Intersection(%(expressions)s))'
                ),
                output_field=FloatField(),
            )
        ).order_by('-overlap_area')

        return intersecting.first()

    def resolve_place(self, name: str, threshold: float = 0.3) -> 'Region | None':
        """
        Resolves a community name to a Place region using trigram similarity.

        Tries Place names first, then falls back to City/CDP names and returns
        the Place with the greatest spatial overlap.
        """
        from django.contrib.postgres.search import TrigramWordSimilarity
        from .models import Region

        place = (
            self.filter(type=Region.Type.PLACE)
            .annotate(similarity=TrigramWordSimilarity(name, 'name'))
            .filter(similarity__gte=threshold)
            .order_by('-similarity')
            .first()
        )
        if place:
            return place

        region = (
            self.filter(type__in=[Region.Type.CITY, Region.Type.CDP], boundary__isnull=False)
            .annotate(similarity=TrigramWordSimilarity(name, 'name'))
            .filter(similarity__gte=threshold)
            .order_by('-similarity')
            .first()
        )
        if region:
            return self.get_containing_region(region, Region.Type.PLACE)

        return None

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

        if not region.boundary or region.boundary.version < boundary.version:
            region.boundary = boundary
            region.save(update_fields=['boundary'])
        return region, created
