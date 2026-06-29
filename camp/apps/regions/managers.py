from typing import Optional

from django.contrib.gis.db import models
from django.contrib.gis.geos.geometry import GEOSGeometry
from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import F, Func, Value
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import FloatField

from camp.apps.regions.querysets import RegionQuerySet
from camp.utils.gis import to_multipolygon


SJV_COUNTIES = {
    'Fresno County',
    'Kern County',
    'Kings County',
    'Madera County',
    'Merced County',
    'San Joaquin County',
    'Stanislaus County',
    'Tulare County',
}


class RegionManager(models.Manager.from_queryset(RegionQuerySet)):
    def counties(self):
        return self.filter(type=self.model.Type.COUNTY, name__in=SJV_COUNTIES)

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

    def search_regions(self, name: str, type: str = None, threshold: float = 0.3):
        """
        Returns a queryset of regions matching name by trigram similarity,
        ordered by descending similarity score. Optionally scoped to a region type.
        """
        qs = self.annotate(similarity=TrigramWordSimilarity(name, 'name'))
        if type:
            qs = qs.filter(type=type)
        return qs.filter(similarity__gte=threshold).order_by('-similarity')

    def resolve_place(self, name: str, type: str = None, threshold: float = 0.3) -> 'Region | None':
        """
        Resolves a community name to a single best-match region.

        With a type, returns the top similarity match within that type.
        Without a type, tries Place names first, then falls back to City/CDP
        names and returns the Place with the greatest spatial overlap.
        """
        from .models import Region

        if type:
            return self.search_regions(name, type=type, threshold=threshold).first()

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
        boundary_metadata: Optional[dict] = None,
    ) -> 'Region':
        from .models import Region, Boundary
        region_defaults = {'name': name, 'slug': slug}
        if metadata is not None:
            region_defaults['metadata'] = metadata
        region, created = Region.objects.update_or_create(
            external_id=external_id,
            type=type,
            defaults=region_defaults,
        )

        boundary, _ = Boundary.objects.update_or_create(
            region_id=region.pk,
            version=version,
            defaults={
                'geometry': to_multipolygon(geometry),
                'metadata': boundary_metadata or {}
            }
        )

        if not region.boundary or region.boundary.version < boundary.version:
            region.boundary = boundary
            region.save(update_fields=['boundary'])
        return region, created
