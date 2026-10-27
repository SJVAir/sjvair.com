"""
Query an ArcGIS FeatureServer layer into a GeoDataFrame.

The server returns GeoJSON itself (f=geojson), so no Esri JSON conversion is
needed. A layer returns at most its maxRecordCount features per request and
says so with `exceededTransferLimit`; the query pages on resultOffset until
it doesn't.
"""

import geopandas as gpd
import requests

# (connect, read) seconds. The AQview import runs every 15 minutes; a stalled
# server shouldn't hold a worker.
TIMEOUT = (15, 60)


class ArcGISError(Exception):
    pass


def get(url, where='1=1', fields='*', session=None, timeout=TIMEOUT):
    '''
    Every feature of the layer at `url` matching `where`, in EPSG:4326.
    `fields` is '*' or a list of field names.
    '''
    session = session or requests.Session()
    params = {
        'where': where,
        'outFields': fields if isinstance(fields, str) else ','.join(fields),
        'outSR': '4326',
        'f': 'geojson',
    }

    features = []
    while True:
        response = session.get(f'{url}/query', params={**params, 'resultOffset': len(features)}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        # A failed query still comes back as a 200, with the error in the body.
        if 'error' in data:
            raise ArcGISError(f'{url}: {data["error"]}')

        page = data.get('features', [])
        features.extend(page)
        if not page or not data.get('properties', {}).get('exceededTransferLimit'):
            break

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs='EPSG:4326')
    return gpd.GeoDataFrame.from_features(features, crs='EPSG:4326')
