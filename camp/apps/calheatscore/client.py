from typing import Any, Dict, List, Sequence

import requests


class CalHeatScoreError(Exception):
    pass


class CalHeatScoreClient:
    url = (
        'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/'
        'CalHeatScore_Live_Data_for_API_Use/FeatureServer/0/query'
    )
    fields = ['ZIP_CODE', 'DATE'] + [f'CHS_Day_{day}' for day in range(7)]

    def __init__(self):
        self.session = requests.Session()

    def data(self, zip_codes: Sequence[str]) -> requests.Response:
        # ZIP codes come from internal Region.external_id data, not user
        # input, but quotes are still escaped defensively before building
        # the ArcGIS `where` clause.
        escaped = (z.replace("'", "''") for z in zip_codes)
        where = 'ZIP_CODE IN ({})'.format(','.join(f"'{z}'" for z in escaped))
        params = {
            'where': where,
            'outFields': ','.join(self.fields),
            'returnGeometry': 'false',
            'f': 'json',
        }
        # POST, not GET: the SJV ZIP set (~240 ZIPs) makes a `where` clause
        # long enough to exceed the server's URL length limit, which fails
        # as a bare 404 rather than a proper ArcGIS JSON error.
        return self.session.post(self.url, data=params, timeout=30)

    def query(self, zip_codes: Sequence[str]) -> List[Dict[str, Any]]:
        if not zip_codes:
            return []

        response = self.data(zip_codes)
        response.raise_for_status()
        body = response.json()

        if 'error' in body:
            raise CalHeatScoreError(body['error'])

        return [feature['attributes'] for feature in body.get('features', [])]


calheatscore_client = CalHeatScoreClient()
