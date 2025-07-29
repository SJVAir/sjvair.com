import tempfile

import ckanapi
import geopandas as gpd
import requests


def gdf_from_ckan(
    dataset_id: str,
    server: str = 'data.ca.gov',
    resource_name: str = 'Shapefile',
    crs: str = 'EPSG:4326',
    verify: bool = True
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
    return gdf_from_zip(resource['url'], crs=crs, verify=verify)


def gdf_from_zip(
    zipfile: str,
    crs: str = 'EPSG:4326',
    verify: bool = True
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
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            session = requests.Session()
            retries = requests.adapters.Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504, 429, 404, 400],
                allowed_methods=['GET']
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retries)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            print(f'Downloading shapefile from:\n{zipfile}\n')
            try:
                response = session.get(zipfile, verify=verify)
                response.raise_for_status()
            except requests.RequestException as e:
                error_msg = e.response.json() if e.response and 'application/json' in e.response.headers.get('Content-Type', '') else str(e)
                raise FileNotFoundError(f'Failed to download shapefile: {error_msg}') from e

            tmpfile.write(response.content)
            tmpfile.flush()
            return gdf_from_zip(tmpfile.name)

    try:
        return gpd.read_file(f'zip://{zipfile}').to_crs(crs)
    except Exception as e:
        raise ValueError(f'Failed to load geodata from zipfile: {zipfile}') from e
