from django.db import models

import geopandas as gpd
from shapely.wkt import loads as load_wkt


class RegionQuerySet(models.QuerySet):
    def to_dataframe(self, fields=None, crs='EPSG:4326'):
        fields = fields or ['sqid', 'name', 'slug', 'type', 'geometry', 'metadata']

        records = []
        for region in self.only(*fields):
            row = {field: getattr(region, field) for field in fields if field != 'geometry'}
            row['geometry'] = load_wkt(region.geometry.wkt)
            records.append(row)

        df = gpd.GeoDataFrame(records, geometry='geometry', crs=crs)
        return df
