from django.contrib.gis.db.models import Union
from django.contrib.gis.geos import GEOSGeometry
from django.db import models

import geopandas as gpd
from shapely.wkt import loads as load_wkt

from camp.utils import maps


class RegionQuerySet(models.QuerySet):
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
