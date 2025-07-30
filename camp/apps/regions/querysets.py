from django.contrib.gis.db.models import Union
from django.contrib.gis.geos import GEOSGeometry
from django.db import models

import geopandas as gpd
from shapely.wkt import loads as load_wkt

from camp.utils import maps


class RegionQuerySet(models.QuerySet):
    def render_map(self, **kwargs):
        geometries = [
            region.boundary.geometry
            for region in self.select_related('boundary')
            if region.boundary and region.boundary.geometry
        ]
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
