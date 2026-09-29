"""
CARB's AB 617 Community and Emission Study Area boundaries, for
`import_ab617_communities`.

The feature service carries one row per (community, boundary type): a
community can have a single combined "Community and Emission Study
Boundary" row, or two separate rows -- a "Community Boundary" and a larger
"Emission Study Area Boundary" -- for the same community (e.g. Shafter).
`group_by_community` buckets rows by the community's short code (SHORTN) so
the importer can pick which geometry is the region's current boundary and
which (if any) is kept as a second, non-current Boundary version.
"""

import requests

FEATURES_URL = (
    'https://services6.arcgis.com/x7ftScCDR8g2kVFB/arcgis/rest/services/'
    'Final_AB_617_Community_and_Emission_Study_Area_Boundaries/FeatureServer/0/query'
)
FEATURES_PARAMS = {
    'where': '1=1',
    'outFields': '*',
    'outSR': '4326',
    'f': 'geojson',
}

FINAL_STATUS = 'Final'

COMMUNITY_BOUNDARY = 'Community Boundary'
EMISSION_STUDY_BOUNDARY = 'Emission Study Area Boundary'
COMBINED_BOUNDARY = 'Community and Emission Study Boundary'

# The Boundary.version each boundary type is stored under. A plain word
# rather than a date -- these aren't revisions of the same boundary over
# time, they're different boundary types CARB publishes for a community.
BOUNDARY_VERSIONS = {
    COMMUNITY_BOUNDARY: 'community',
    EMISSION_STUDY_BOUNDARY: 'emission_study_area',
    COMBINED_BOUNDARY: 'combined',
}


def fetch_features():
    """Every AB 617 boundary feature as GeoJSON."""
    response = requests.get(FEATURES_URL, params=FEATURES_PARAMS, timeout=120)
    response.raise_for_status()
    return response.json()['features']


def group_by_community(features):
    """
    {short_name: {'properties': <feature properties, from the last row seen>,
                   'boundaries': {boundary_type: geojson_geometry_dict}}}

    Non-"Final" rows (draft/proposed boundaries) are skipped. Fields other
    than BNDRYTYPE are the same across a community's rows, so whichever row
    is seen last for a given community supplies `properties`.
    """
    grouped = {}
    for item in features:
        props = item['properties']
        if props.get('BNDRYSTATDESC') != FINAL_STATUS:
            continue

        code = props['SHORTN']
        entry = grouped.setdefault(code, {'properties': props, 'boundaries': {}})
        entry['properties'] = props
        entry['boundaries'][props['BNDRYTYPE']] = item['geometry']

    return grouped


def primary_boundary_type(boundaries):
    """
    Which of a community's boundary rows becomes the region's current
    boundary: the standalone Community Boundary when there is one (it's the
    community itself, not the larger area CARB studied emissions across),
    else the combined Community-and-Emission-Study row. A community with
    only an Emission Study Area Boundary (no community-specific geometry)
    has nothing to import.
    """
    if COMMUNITY_BOUNDARY in boundaries:
        return COMMUNITY_BOUNDARY
    if COMBINED_BOUNDARY in boundaries:
        return COMBINED_BOUNDARY
    return None
