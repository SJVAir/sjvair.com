from django.contrib.gis.db import models
from django.contrib.gis.db.models import Count, FloatField, Func, F, OuterRef, Subquery, Union
from django.contrib.gis.db.models.functions import Intersection
from django.contrib.gis.geos import GEOSGeometry
from django.db.models.functions import NullIf

import geopandas as gpd
from shapely.wkt import loads as load_wkt

from camp.utils import maps


class RegionQuerySet(models.QuerySet):
    def with_monitor_count(self):
        from camp.apps.monitors.models import Monitor

        # Subquery returns a single count of monitors intersecting the region geometry
        monitor_count_query = (Monitor.objects
            .filter(position__intersects=OuterRef('boundary__geometry'))
            .order_by()  # Required to use Subquery safely
            .annotate(count=Func(F('id'), function='Count'))
            .values('count')
        )

        return self.annotate(
            monitor_count=Subquery(monitor_count_query, output_field=models.IntegerField())
        )

    def render_map(self, **kwargs):
        geometries = [region.boundary.geometry for region in self.select_related('boundary')]
        return maps.from_geometries(*geometries, **kwargs)

    def to_dataframe(self, fields=None, crs='EPSG:4326'):
        fields = fields or [
            'sqid', 'name', 'slug', 'type',
            'boundary__geometry', 'boundary__metadata'
        ]

        records = []
        for row in self.values(*fields):
            record = {k: row[k] for k in fields if not k.startswith('boundary__')}
            record['geometry'] = load_wkt(row['boundary__geometry'].wkt)
            record['metadata'] = row['boundary__metadata']
            records.append(record)

        return gpd.GeoDataFrame(records, geometry='geometry', crs=crs)

    def intersects(self, geometry: GEOSGeometry):
        """
        Filters regions that intersect the given geometry.
        """
        return self.filter(boundary__geometry__intersects=geometry)

    def contained_within(self, geometry: GEOSGeometry, min_fraction: float = 0.99):
        """
        Filters regions that are (essentially) entirely inside the given
        geometry: at least `min_fraction` of the region's own area must fall
        within it. Regions that only touch its border, or that genuinely
        straddle it (e.g. a congressional district spanning two counties),
        are excluded - "within this area" callers want regions inside it,
        not merely overlapping it.

        This is deliberately not a strict ST_Within. Tract/ZIP boundaries
        come from different sources than county boundaries and disagree by
        hairline slivers, so a tract that is unambiguously in Fresno County
        can still poke a few metres into Madera; strict containment drops
        ~15% of Fresno's tracts and a third of its ZIPs on real data. Those
        excursions are all well under 0.1% of area, while the smallest
        genuine straddle is several percent, so 99% separates the two.
        """
        overlap = Func(
            Intersection('boundary__geometry', geometry),
            function='ST_Area', output_field=FloatField(),
        )
        area = Func('boundary__geometry', function='ST_Area', output_field=FloatField())
        return (self
            # ST_Intersects first so the spatial index prunes candidates
            # before the (expensive) intersection area is computed.
            .filter(boundary__geometry__intersects=geometry)
            .annotate(overlap_fraction=overlap / NullIf(area, 0.0))
            .filter(overlap_fraction__gte=min_fraction)
        )

    def combined_geometry(self) -> GEOSGeometry:
        """
        Returns a MultiPolygon representing the union of all geometries in the queryset.
        """
        return self.aggregate(combined=Union('boundary__geometry'))['combined']


class BoundaryQuerySet(models.QuerySet):
    def render_map(self, **kwargs):
        geometries = [boundary.geometry for boundary in self]
        return maps.from_geometries(*geometries, **kwargs)

    def to_dataframe(self, fields=None, crs='EPSG:4326') -> gpd.GeoDataFrame:
        """
        Convert the queryset to a GeoDataFrame.
        Assumes 'geometry' is a GEOSGeometry field and uses WGS84 (EPSG:4326) by default.
        """
        fields = fields or [
            'id', 'region_id', 'region__external_id', 'region__name',
            'version', 'created', 'metadata', 'geometry'
        ]

        records = []
        for row in self.values(*fields):
            row['geometry'] = load_wkt(row['geometry'].wkt)
            records.append(row)

        return gpd.GeoDataFrame(records, geometry='geometry', crs=crs)
