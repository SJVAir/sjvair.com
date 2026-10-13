"""
California air districts from CARB's "California Air District Boundaries"
layer, for `import_air_districts`.

The layer carries a code and an all-caps name per feature, and a district with
several parts comes as several features. Display names and contacts come from
`datafiles/air-districts.yaml`, captured from CARB's district directory, since
the layer has neither.
"""

import json

import requests

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon

from camp.utils.datafiles import datafile

FEATURES_URL = (
    'https://services6.arcgis.com/x7ftScCDR8g2kVFB/arcgis/rest/services/'
    'Air_District_WFL1/FeatureServer/0/query'
)
FEATURES_PARAMS = {
    'where': '1=1',
    'outFields': 'Air_District_Code,Air_District_Name',
    'outSR': '4326',
    'f': 'geojson',
}
DIRECTORY_FILE = 'air-districts.yaml'
DIRECTORY_FIELDS = ('carb_url', 'complaints_url', 'phone')


def fetch_features():
    """Every district feature as GeoJSON (about 8 MB, 47 features for 35 districts)."""
    response = requests.get(FEATURES_URL, params=FEATURES_PARAMS, timeout=120)
    response.raise_for_status()
    return response.json()['features']


def _polygons(geometry):
    return list(geometry) if geometry.geom_type == 'MultiPolygon' else [geometry]


def group_by_code(features):
    """{code: {'name': <layer name>, 'geometry': MultiPolygon}}, one entry per district."""
    grouped = {}
    for item in features:
        props = item['properties']
        code = props['Air_District_Code']
        geometry = GEOSGeometry(json.dumps(item['geometry']), srid=4326)
        entry = grouped.setdefault(code, {'name': props['Air_District_Name'], 'polygons': []})
        entry['polygons'].extend(_polygons(geometry))
    return {
        code: {'name': entry['name'], 'geometry': MultiPolygon(*entry['polygons'], srid=4326)}
        for code, entry in grouped.items()
    }


def load_directory():
    """{code: {'name', 'carb_url', 'complaints_url', 'phone'}} from the datafile."""
    return datafile(DIRECTORY_FILE)


def title_case(name):
    """'SAN JOAQUIN VALLEY UNIFIED APCD' -> 'San Joaquin Valley Unified APCD'."""
    words = []
    for word in name.split():
        words.append(word if word in ('APCD', 'AQMD') else word.capitalize())
    return ' '.join(words)
