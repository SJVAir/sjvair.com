import statistics
from typing import List, Dict

import geopandas as gpd

from django.contrib.gis.db import models
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata, maps


def to_geos_4326(geometry, srid=None):
    """
    Converts a Shapely or GEOS geometry to GEOSGeometry with SRID 4326.
    If `srid` is not provided, defaults to 3857.
    """
    if isinstance(geometry, GEOSGeometry):
        return geometry.transform(4326, clone=True)

    srid = srid or 3857  # Default fallback
    geos = GEOSGeometry(geometry.wkt, srid=srid)
    geos.transform(4326)
    return geos


def summarize_diffs(diffs: List[Dict]):
    areas = [d['diff_area'] for d in diffs]
    print('\n--- Geometry Difference Summary ---')
    print(f'Total tracts compared: {len(areas)}')
    print(f'Min area difference: {min(areas):,.2f} mi²')
    print(f'Max area difference: {max(areas):,.2f} mi²')
    print(f'Mean area difference: {statistics.mean(areas):,.2f} mi²')
    print(f'Median area difference: {statistics.median(areas):,.2f} mi²')


def print_top_diffs(diffs: List[Dict], tract_to_county: dict):
    print('\n--- Top 15 Most Different Geometries ---')
    for d in sorted(diffs, key=lambda x: x['diff_area'], reverse=True)[:15]:
        gdf_county = tract_to_county.get(d['geoid'], 'Unknown')
        ces_geom_county = get_county_for_geometry(d['ces4_geom'])
        db_geom_county = get_county_for_geometry(d['db_geom'])
        print(f"{d['geoid']}: {d['diff_area']:,.2f} mi² (gdf: {gdf_county} / ces: {ces_geom_county} / db: {db_geom_county})")


def print_missing_diffs(gdf, missing_rows, tract_to_county):
    print('\n--- Missing Tracts With 2020 Boundary Present ---')
    for row in missing_rows:
        external_id = row.Tract
        try:
            boundary = Boundary.objects.get(
                region__type=Region.Type.TRACT,
                region__external_id=external_id,
                version='2020'
            )
        except Boundary.DoesNotExist:
            continue

        gdf_county = tract_to_county.get(external_id, 'Unknown')
        ces_geom_county = get_county_for_geometry(to_geos_4326(row.geometry, srid=gdf.crs.to_epsg()))
        db_geom_county = get_county_for_geometry(boundary.geometry)

        ces_geom = maps.to_shape(row.geometry)
        db_geom = maps.to_shape(boundary.geometry)
        diff_area = ces_geom.symmetric_difference(db_geom).area / 2.59e+6

        print(f'{external_id}: {diff_area:,.2f} mi² (gdf: {gdf_county} / ces: {ces_geom_county} / db: {db_geom_county})')


def get_county_for_geometry(geom):
    """
    Returns the name of the county that most overlaps the given geometry.
    Falls back to 'Unknown' if no intersecting counties found.
    """
    geom = to_geos_4326(geom)
    counties = Region.objects.filter(type=Region.Type.COUNTY).select_related('boundary')

    max_area = 0
    best_match = None

    for county in counties:
        county_geom = county.boundary.geometry
        if county_geom and geom.intersects(county_geom):
            intersection = geom.intersection(county_geom)
            area = intersection.area
            if area > max_area:
                max_area = area
                best_match = county.name

    return best_match or 'Unknown'


class Command(BaseCommand):
    help = 'Compare CES4 tracts against 2010 census tracts'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan(
            dataset_id='calenviroscreen-4-0',
            resource_name='CalEnviroScreen 4.0 Results Shapefile',
            string_fields=['Tract'],
        )
        gdf = geodata.filter_by_overlap(gdf, counties_gdf.unary_union, 0.25)
        gdf['Tract'] = gdf['Tract'].astype(str).str.zfill(11)

        boundary_map = {
            b.region.external_id: b.geometry
            for b in Boundary.objects.filter(region__type=Region.Type.TRACT, version='2010')
        }

        diffs = []
        missing = []

        for _, row in gdf.iterrows():
            geoid = row.Tract
            ces_geom = maps.to_shape(row.geometry)
            db_geom = boundary_map.get(geoid)

            if not db_geom:
                print('MISSING BOUNDARY:', geoid)
                missing.append(row)
                continue

            db_geom = maps.to_shape(db_geom)
            diff_geom = ces_geom.symmetric_difference(db_geom)

            if not diff_geom.is_empty:
                diffs.append({
                    'geoid': geoid,
                    'diff_area': diff_geom.area / 2.59e+6,
                    'ces4_geom': ces_geom,
                    'db_geom': db_geom,
                    'diff_geom': diff_geom,
                })

        tract_to_county = dict(zip(gdf['Tract'], gdf['County']))

        summarize_diffs(diffs)
        print_top_diffs(diffs, tract_to_county)
        print(f'\n--- CES4 Tracts missing in our database: {len(missing)} ---')
        print_missing_diffs(gdf, missing, tract_to_county)
