import hashlib
import tempfile

from pathlib import Path
from typing import Optional, Sequence, Union

import ckanapi
import geopandas as gpd
import pandas as pd
import requests

from shapely.geometry.base import BaseGeometry

GEODATA_CACHE_DIR = Path(tempfile.gettempdir()) / 'geodata-cache'
GEODATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def filter_by_overlap(
    gdf: gpd.GeoDataFrame,
    reference_geom: BaseGeometry,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    """
    Filters rows in a GeoDataFrame where the geometry overlaps with a reference geometry
    by at least the given fraction of its own area.

    Args:
        gdf: The GeoDataFrame to filter.
        reference_geom: A base geometry (e.g., a unary_union of other geometries) to compare against.
        threshold: Minimum fraction of each geometry’s area that must overlap with reference_geom.

    Returns:
        A filtered GeoDataFrame containing only geometries meeting the threshold.
    """
    def sufficient_overlap(geom):
        if geom.is_empty or geom.area == 0 or not geom.intersects(reference_geom):
            return False
        intersection_area = geom.intersection(reference_geom).area
        return (intersection_area / geom.area) >= threshold

    mask = gdf.geometry.apply(sufficient_overlap)
    return gdf[mask].copy().reset_index(drop=True)

def filter_by_counties(
    gdf: gpd.GeoDataFrame,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    from camp.apps.regions.models import Region
    counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
    gdf = filter_by_overlap(gdf, counties_gdf.unary_union, threshold=threshold)
    return gdf


def stringify_gdf_fields(
    gdf: gpd.GeoDataFrame,
    columns: Optional[Sequence[str]] = None
) -> gpd.GeoDataFrame:
    """
    Converts specified columns in a GeoDataFrame to strings, preserving the original geometry.

    Args:
        gdf: The input GeoDataFrame.
        columns: Optional list of column names to convert. If None, all non-geometry columns are converted.

    Returns:
        A copy of the GeoDataFrame with specified columns converted to strings.

    Notes:
        - Missing values (NaN) are preserved as empty strings.
        - Geometry column is left unmodified.
    """

    def clean_value(val):
        if pd.isnull(val):
            return ''
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)

    gdf = gdf.copy()

    if columns is None:
        columns = [col for col in gdf.columns if col != gdf.geometry.name]

    for col in columns:
        gdf[col] = gdf[col].map(clean_value)
    return gdf


def gdf_from_ckan(
    dataset_id: str,
    server: str = 'data.ca.gov',
    resource_name: str = 'Shapefile',
    encoding: str = 'utf-8',
    crs: str = 'EPSG:4326',
    verify: bool = True,
    string_fields: Union[bool, Sequence[str]] = False,
    limit_to_counties: bool = False,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    """
    Fetch a GeoDataFrame from a CKAN-backed open data portal.

    This function queries a CKAN instance (e.g. data.ca.gov) for a dataset by ID,
    locates the specified resource (typically a shapefile), downloads it, and
    loads it into a GeoDataFrame in the specified coordinate reference system.

    Args:
        dataset_id: The CKAN dataset/package ID or slug.
        server: The CKAN server hostname (default is 'data.ca.gov').
        resource_name: The display name of the resource to fetch (default is 'Shapefile').
        crs: Coordinate reference system to reproject the data to (default is 'EPSG:4326').
        verify: Whether to verify SSL certificates when downloading (default: True).

    Returns:
        GeoDataFrame containing the spatial data from the requested CKAN resource.

    Raises:
        ValueError: If the resource with the given name is not found in the dataset.
        FileNotFoundError: If the shapefile download fails.
        ValueError: If the shapefile cannot be read or parsed.
    """
    ckan = ckanapi.RemoteCKAN(f'https://{server}')
    package = ckan.action.package_show(id=dataset_id)
    resource = next((r for r in package['resources'] if r['name'] == resource_name), None)
    if not resource:
        raise ValueError(f'Resource not found: {resource_name}')
    return gdf_from_zip(
        zipfile=resource['url'],
        encoding=encoding,
        crs=crs,
        verify=verify,
        string_fields=string_fields,
        limit_to_counties=limit_to_counties,
        threshold=threshold,
    )


def gdf_from_zip(
    zipfile: str,
    verify: bool = True,
    encoding: str = 'utf-8',
    crs: str = 'EPSG:4326',
    string_fields: Union[bool, Sequence[str]] = False,
    limit_to_counties: bool = False,
    threshold: float = 0.5
) -> gpd.GeoDataFrame:
    """
    Loads a GeoDataFrame from a zipfile path or URL.

    Args:
        zipfile: Path to local zipfile or URL pointing to zip shapefile.
        crs: Coordinate reference system to convert to.
        verify: Whether to verify SSL certificates (only used if zipfile is a URL).

    Returns:
        GeoDataFrame in the specified CRS.

    Raises:
        FileNotFoundError: If the remote file cannot be downloaded.
        ValueError: If reading the shapefile fails.
    """
    if zipfile.startswith('http'):
        # Generate safe cache filename using SHA256 hash of the URL
        url_hash = hashlib.sha256(zipfile.encode()).hexdigest()[:16]
        cache_path = GEODATA_CACHE_DIR / f'{url_hash}.zip'

        if cache_path.exists():
            print(f'Using cached shapefile: {cache_path}')
            return gdf_from_zip(
                zipfile=str(cache_path),
                encoding=encoding,
                crs=crs,
                string_fields=string_fields,
                limit_to_counties=limit_to_counties,
                threshold=threshold,
            )

        retries = requests.adapters.Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504, 429, 404, 400, 202],
            allowed_methods=['GET']
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retries)
        session = requests.Session()
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; SJVAir Downloader)',
            'Accept': '*/*',
        }

        print('Downloading file:')
        print(f'-> URL: {zipfile}')
        print(f'-> Dest: {cache_path}\n')
        response = session.get(zipfile, verify=verify, headers=headers)
        response.raise_for_status()

        cache_path.write_bytes(response.content)
        return gdf_from_zip(
            zipfile=str(cache_path),
            encoding=encoding,
            crs=crs,
            string_fields=string_fields,
            limit_to_counties=limit_to_counties,
            threshold=threshold,
        )

    gdf = gpd.read_file(f'zip://{zipfile}', encoding=encoding).to_crs(crs)

    if string_fields is True:
        gdf = stringify_gdf_fields(gdf)
    elif isinstance(string_fields, (list, tuple)):
        gdf = stringify_gdf_fields(gdf, string_fields)

    if limit_to_counties:
        gdf = filter_by_counties(gdf, threshold=threshold)

    return gdf
