import hashlib
import tempfile
import zipfile

from pathlib import Path
from typing import Iterator, Optional, Sequence, Union

import ckanapi
import fiona
import geopandas as gpd
import pandas as pd

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from camp.utils import gis
from camp.utils.http import stream_to_disk

GEODATA_CACHE_DIR = Path(tempfile.gettempdir()) / 'geodata-cache'
GEODATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def remap_gdf_boundaries(
    source: pd.DataFrame,
    target: gpd.GeoDataFrame,
    rel: pd.DataFrame,
    source_geoid_col: str = 'geoid',
    target_geoid_col: str = 'geoid',
    rel_source_col: Optional[str] = None,
    rel_target_col: Optional[str] = None,
    area_field: str = 'AREALAND_PART',
    include_fields: Optional[list[str]] = None,
    rate_fields: Optional[list[str]] = None, 
    count_fields: Optional[list[str]] = None, 
) -> gpd.GeoDataFrame:
    """
    Remap metadata from source tracts to target geometries using area-based weighting.

    Parameters:
        source: DataFrame with metadata, keyed by source_geoid_col
        target: GeoDataFrame with target geometries
        rel: Census relationship file with GEOID_TRACT_10, GEOID_TRACT_20, and AREALAND_PART
        source_geoid_col: Name of GEOID column in `source`
        target_geoid_col: Name of GEOID column in `target`
        area_field: Column in `rel` to use for weighting (usually 'AREALAND_PART')
        include_fields: Columns from source to include; if None, include all (except geometry and geoid)

    Returns:
        GeoDataFrame shaped like `target`, with remapped metadata attached
    """
    rel = rel.copy()

    if rel_source_col is None or rel_target_col is None:
        raise ValueError('You must explicitly provide rel_source_col and rel_target_col')

    rel['GEOID_SOURCE'] = rel[rel_source_col].astype(str).str.zfill(11)
    rel['GEOID_TARGET'] = rel[rel_target_col].astype(str).str.zfill(11)

    # Merge rel with source metadata
    merged = rel.merge(source, left_on='GEOID_SOURCE', right_on=source_geoid_col, how='inner')

    # Compute weights
    merged[area_field] = pd.to_numeric(merged[area_field], errors='coerce')
    merged['weight'] = merged[area_field] / merged.groupby('GEOID_SOURCE')[area_field].transform('sum')

    # Warn if mappings are partial
    check = merged.groupby('GEOID_SOURCE')['weight'].sum().reset_index()
    bad = check[check['weight'] < 0.99]
    print(f'{"⚠️" if len(bad) else "✅"} {len(bad)} tracts have weights summing to less than 0.99')

    if rate_fields and count_fields:
        counts_weighted = merged.copy()
        for col in count_fields:
            counts_weighted[col] = counts_weighted[col] * counts_weighted['weight']
        counts_result = counts_weighted.groupby('GEOID_TARGET')[count_fields].sum().reset_index()

        #Metric based variables EX: ozone -> ppm
        rates_result = merged.groupby('GEOID_TARGET').apply(
            lambda df: pd.Series({
                col: (df[col] * df['weight']).sum() / df['weight'].sum()
                for col in rate_fields
            })
        ).reset_index()
        aggregated = counts_result.merge(rates_result, on='GEOID_TARGET', how='outer')
        non_numeric_cols = [col for col in source.columns if col not in rate_fields and col not in count_fields] 

    else:
        # Determine columns to carry forward
        if include_fields is None:
            include_fields = [col for col in source.columns if col not in (source_geoid_col, 'geometry')]

        numeric_cols = [col for col in include_fields if pd.api.types.is_numeric_dtype(source[col])]
        non_numeric_cols = [col for col in include_fields if col not in numeric_cols]

        # Weighted numeric aggregation
        for col in numeric_cols:
            merged[col] = pd.to_numeric(merged[col], errors='coerce') * merged['weight']
        aggregated = merged.groupby('GEOID_TARGET')[numeric_cols].sum().reset_index()

    # Non-numeric from dominant row
    merged['rank'] = merged.groupby('GEOID_TARGET')['weight'].rank(ascending=False, method='first')
    dominant_rows = merged.loc[merged['rank'] == 1, ['GEOID_TARGET'] + non_numeric_cols]

    # Merge both sets of data
    result = aggregated.merge(dominant_rows, on='GEOID_TARGET', how='left')
    if 'geometry' in result.columns:
        result = result.drop(columns='geometry')
        
    # Attach geometry
    
    out = target[[target_geoid_col, 'geometry']].rename(columns={target_geoid_col: 'GEOID_TARGET'})
    out = out.merge(result, on='GEOID_TARGET', how='left')
    out = out.drop(columns=['Tract'], errors='ignore')
    print(out)
    return gpd.GeoDataFrame(out, geometry='geometry', crs=target.crs).rename(columns={'GEOID_TARGET': source_geoid_col})


def filter_by_overlap(
    series_iter: Iterator[gpd.GeoSeries],
    reference_geom: BaseGeometry,
    threshold: float = 0.5
) -> Iterator[gpd.GeoSeries]:
    """
    Filters streamed GeoSeries where geometry overlaps with a reference geometry
    by at least the given fraction of its own area.

    Args:
        series_iter: Iterator of GeoSeries rows (streamed from disk).
        reference_geom: Geometry to compare against (e.g., unary_union of counties).
        threshold: Minimum fraction of area that must overlap.

    Yields:
        GeoSeries rows that meet the overlap threshold.
    """
    for series in series_iter:
        geom = series.geometry
        if geom.is_empty or geom.area == 0 or not geom.intersects(reference_geom):
            continue
        intersection_area = geom.intersection(reference_geom).area
        if (intersection_area / geom.area) >= threshold:
            yield series


def load_region_geometry(crs: Optional[str] = gis.EPSG_LATLON):
    from camp.apps.regions.models import Region
    geometry = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe().unary_union
    if crs != gis.EPSG_LATLON:
        geometry = (
            gpd.GeoSeries([geometry], crs=gis.EPSG_LATLON)
            .to_crs(crs)
            .iloc[0]
        )
    return geometry


def gdf_from_ckan(*args, **kwargs) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(iter_from_ckan(*args, **kwargs))
    if 'geometry' not in gdf.columns:
        gdf.set_geometry('geometry', inplace=True)
    return gdf

def gdf_from_url(*args, **kwargs) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(iter_from_url(*args, **kwargs))
    if 'geometry' not in gdf.columns:
        gdf.set_geometry('geometry', inplace=True)
    return gdf

def gdf_from_zip(*args, **kwargs) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(iter_from_zip(*args, **kwargs))
    if 'geometry' not in gdf.columns:
        gdf.set_geometry('geometry', inplace=True)
    return gdf


def stream_filtered_gdf(
    path: str,
    crs: str = gis.EPSG_LATLON,
    encoding: str = 'utf-8',
    limit_to_region: bool = False,
    string_fields: Union[bool, Sequence[str]] = False,
) -> Iterator[gpd.GeoSeries]:
    def clean_value(val):
        if pd.isnull(val):
            return ''
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)

    with fiona.open(f'zip://{path}', encoding=encoding) as src:
        iterable = src
        if limit_to_region:
            region = load_region_geometry(src.crs)
            iterable = src.filter(bbox=region.bounds)

        for i, feat in enumerate(iterable):
            geometry = shape(feat['geometry'])
            props = feat['properties']

            if string_fields is True:
                props = {k: clean_value(v) for k, v in props.items()}
            elif isinstance(string_fields, (list, tuple)):
                props = {
                    k: clean_value(v) if k in string_fields else v
                    for k, v in props.items()
                }

            gdf = gpd.GeoDataFrame([props], geometry=[geometry], crs=src.crs)
            if src.crs and src.crs.to_string() != crs:
                gdf = gdf.to_crs(crs)

            yield gdf.iloc[0]


def iter_from_ckan(
    dataset_id: str,
    server: str = 'data.ca.gov',
    resource_name: str = 'Shapefile',
    encoding: str = 'utf-8',
    crs: str = gis.EPSG_LATLON,
    verify: bool = True,
    string_fields: Union[bool, Sequence[str]] = False,
    limit_to_region: bool = False,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    """
    Fetch a GeoDataFrame from a CKAN-backed open data portal.

    This function queries a CKAN instance (e.g. data.ca.gov) for a dataset by ID,
    locates the specified resource (typically a shapefile), downloads it, and
    loads it into a GeoDataFrame in the specified coordinate reference system.
    """
    ckan = ckanapi.RemoteCKAN(f'https://{server}')
    package = ckan.action.package_show(id=dataset_id)
    resource = next((r for r in package['resources'] if r['name'] == resource_name), None)
    if not resource:
        raise ValueError(f'\nResource not found: {resource_name}')

    return iter_from_url(
        url=resource['url'],
        encoding=encoding,
        crs=crs,
        verify=verify,
        string_fields=string_fields,
        limit_to_region=limit_to_region,
        threshold=threshold,
    )


def iter_from_url(
    url: str,
    verify: bool = True,
    encoding: str = 'utf-8',
    crs: str = gis.EPSG_LATLON,
    string_fields: Union[bool, Sequence[str]] = False,
    limit_to_region: bool = False,
    threshold: float = 0.5,
) -> gpd.GeoDataFrame:
    """
        Get a GDF from a URL.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    cache_path = GEODATA_CACHE_DIR / f'{url_hash}.zip'
    if not cache_path.exists():
        print('\nDownloading dataset:')
        print(f'-> {url}')
        print(f'-> {cache_path}')
        stream_to_disk(url=url, dest=cache_path, verify=verify)
        with zipfile.ZipFile(cache_path) as z:
            if bad := z.testzip():
                cache_path.unlink(missing_ok=True)
                raise ValueError(f'Corrupt ZIP member: {bad}')

    return iter_from_zip(
        path=cache_path,
        encoding=encoding,
        crs=crs,
        verify=verify,
        string_fields=string_fields,
        limit_to_region=limit_to_region,
        threshold=threshold,
    )


def iter_from_zip(
    path: str,
    verify: bool = True,
    encoding: str = 'utf-8',
    crs: str = gis.EPSG_LATLON,
    string_fields: Union[bool, Sequence[str]] = False,
    limit_to_region: bool = False,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    """
    Loads a GeoDataFrame from a zipfile path.
    """
    print('\nLoading gdf from...')
    print(f'-> {path}')

    results = stream_filtered_gdf(
        path=path,
        encoding=encoding,
        crs=crs,
        limit_to_region=limit_to_region,
    )

    if limit_to_region:
        results = filter_by_overlap(
            results,
            load_region_geometry(crs),
            threshold=threshold
        )

    return results
