"""
Facility coordinates from CARB's Pollution Mapping Tool.

The tool's map draws every CEIDARS facility from a marker file per inventory
year (`ceifacmarkerdata{year}.txt`: CO, AB, DIS, FACID, FACILITY, LATITUDE,
LONGITUDE), keyed exactly as our facilities are (county number, district,
FACID). Files exist from 2022 on; earlier years redirect to an error page.
The 2022 file is tab-delimited, the later ones comma-delimited.

Checked against Census street matches (1,248 SJV facilities, 2026-09-23):
median 85 m apart, 90% within 500 m, 95% within 1 km, ~1.6% more than 5 km
off. How a point is chosen from these and the geocoders is in
locations.choose_point.
"""

import csv
import io
import logging

import requests

from django.contrib.gis.geos import Point

logger = logging.getLogger(__name__)

MARKER_URL = 'https://www.arb.ca.gov/carbapps/pollution-map/data/ceifacmarkerdata{year}.txt'
FIRST_YEAR = 2022


def parse_markers(text):
    """{(county_code, district, facid): Point} from one marker file's text."""
    first_line = text.split('\n', 1)[0]
    delimiter = '\t' if '\t' in first_line else ','
    markers = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=delimiter):
        try:
            key = (int(row['CO']), row['DIS'].strip(), int(float(row['FACID'])))
            point = Point(float(row['LONGITUDE']), float(row['LATITUDE']), srid=4326)
        except (KeyError, TypeError, ValueError):
            continue
        markers[key] = point
    return markers


def fetch_markers(years):
    """
    Every marker file in `years` that CARB publishes, merged with the newest
    year winning. Returns (markers, [years found]). A year CARB hasn't
    published (a redirect or an error) is skipped.
    """
    markers = {}
    found = []
    for year in sorted(years):
        response = requests.get(
            MARKER_URL.format(year=year),
            headers={'User-Agent': 'Mozilla/5.0 (SJVAir)'},
            timeout=60,
            allow_redirects=False,
        )
        if response.status_code != 200:
            logger.info('No CARB marker file for %s (HTTP %s)', year, response.status_code)
            continue
        markers.update(parse_markers(response.text))
        found.append(year)
    return markers, found
